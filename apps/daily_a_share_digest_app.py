#!/usr/bin/env python3
"""Daily A-share dynamic digest Streamlit app.

This is a local research dashboard only. It does not provide investment advice.
"""

from __future__ import annotations

import dataclasses
import concurrent.futures
import datetime as dt
import html
import json
import math
import re
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st


TENCENT_URL = "http://qt.gtimg.cn/q={symbols}"
EASTMONEY_STOCK_URL = (
    "https://push2.eastmoney.com/api/qt/stock/get"
    "?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170,f171"
)
EASTMONEY_KLINE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid={secid}&klt=101&fqt=1&lmt={limit}"
    "&end=20500101"
    "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
)
SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sz399300"

DEFAULT_CODES = "600487 000758 000733 603678 000636 600522 603601 600396 002491 002241 603005 002456 000988"
DEFAULT_POSITIONS = "600487 200 68.62\n002491 100 22.05"

SECTORS = {
    "军工电子/电子元件": ["000733", "603678", "000636"],
    "光通信/海缆/CPO": ["600487", "600522", "002491", "000988"],
    "稀土/有色/磁材": ["000758", "600111", "600366"],
    "商业航天/材料": ["603601", "600118", "002025"],
    "电力/能源/装备": ["600396", "000400", "600312"],
    "消费电子/AI硬件": ["002241", "603005", "002456"],
}


@dataclasses.dataclass
class Quote:
    code: str
    name: str
    price: float
    pct: float
    change: float
    high: float
    low: float
    prev_close: float
    avg_price: float | None
    amount: float | None
    turnover: float | None
    source: str

    @property
    def lot_cash(self) -> float:
        return self.price * 100


def fetch_url(url: str, encoding: str = "utf-8", timeout: float = 8) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AShareDailyDigest/1.0",
            "Referer": "https://finance.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="replace")


def parse_float(value: object, scale: float = 1.0) -> float:
    if value in (None, "", "-"):
        return 0.0
    return float(value) / scale


def market_prefix(code: str) -> str:
    return "sh" if code.startswith(("6", "9")) else "sz"


def eastmoney_secid(code: str) -> str:
    return f"{'1' if code.startswith(('6', '9')) else '0'}.{code}"


@st.cache_data(ttl=20)
def fetch_tencent_quotes(codes: tuple[str, ...]) -> dict[str, Quote]:
    symbols = ",".join(f"{market_prefix(code)}{code}" for code in codes)
    text = fetch_url(TENCENT_URL.format(symbols=urllib.parse.quote(symbols, safe=",")), "gbk")
    quotes: dict[str, Quote] = {}
    for line in text.splitlines():
        match = re.search(r'v_(?:sh|sz)(\d{6})="(.*)";', line)
        if not match:
            continue
        code, payload = match.groups()
        fields = payload.split("~")
        if len(fields) < 49:
            continue
        try:
            price = parse_float(fields[3])
            prev_close = parse_float(fields[4])
            high = parse_float(fields[33])
            low = parse_float(fields[34])
            change = parse_float(fields[31])
            pct = parse_float(fields[32])
            amount = parse_float(fields[37]) * 10000 if fields[37] else None
            turnover = parse_float(fields[38]) if len(fields) > 38 else None
            avg_price = parse_float(fields[51]) if len(fields) > 51 else None
        except (ValueError, IndexError):
            continue
        quotes[code] = Quote(
            code=code,
            name=fields[1],
            price=price,
            pct=pct,
            change=change,
            high=high,
            low=low,
            prev_close=prev_close,
            avg_price=avg_price,
            amount=amount,
            turnover=turnover,
            source="Tencent",
        )
    return quotes


def fetch_eastmoney_quote(code: str) -> Quote | None:
    try:
        text = fetch_url(EASTMONEY_STOCK_URL.format(secid=eastmoney_secid(code)))
        data = json.loads(text).get("data") or {}
    except Exception:
        return None
    if not data:
        return None
    price = parse_float(data.get("f43"), 100)
    prev_close = parse_float(data.get("f60"), 100)
    return Quote(
        code=code,
        name=str(data.get("f58") or code),
        price=price,
        pct=parse_float(data.get("f170"), 100),
        change=price - prev_close if prev_close else 0.0,
        high=parse_float(data.get("f44"), 100),
        low=parse_float(data.get("f45"), 100),
        prev_close=prev_close,
        avg_price=None,
        amount=parse_float(data.get("f48")),
        turnover=parse_float(data.get("f168"), 100),
        source="Eastmoney",
    )


def parse_codes(text: str) -> list[str]:
    return re.findall(r"\b\d{6}\b", text or "")


def parse_positions(text: str) -> pd.DataFrame:
    rows = []
    for line in (text or "").splitlines():
        parts = re.split(r"[\s,，:：]+", line.strip())
        if len(parts) < 3 or not re.fullmatch(r"\d{6}", parts[0]):
            continue
        try:
            rows.append({"代码": parts[0], "股数": int(float(parts[1])), "成本": float(parts[2])})
        except ValueError:
            continue
    return pd.DataFrame(rows)


@st.cache_data(ttl=20)
def get_quotes(codes: tuple[str, ...]) -> pd.DataFrame:
    codes = tuple(sorted({code for code in codes if re.fullmatch(r"\d{6}", code)}))
    quotes: dict[str, Quote] = {}
    if codes:
        try:
            quotes = fetch_tencent_quotes(codes)
        except Exception:
            quotes = {}
    for code in codes:
        if code not in quotes:
            q = fetch_eastmoney_quote(code)
            if q:
                quotes[code] = q
    rows = []
    for q in quotes.values():
        rows.append(
            {
                "代码": q.code,
                "名称": q.name,
                "最新价": q.price,
                "涨跌幅%": q.pct,
                "涨跌额": q.change,
                "日高": q.high,
                "日低": q.low,
                "前收": q.prev_close,
                "均价": q.avg_price,
                "成交额": q.amount,
                "换手%": q.turnover,
                "一手资金": q.lot_cash,
                "来源": q.source,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800)
def fetch_kline(code: str, limit: int = 180) -> pd.DataFrame:
    try:
        text = fetch_url(EASTMONEY_KLINE_URL.format(secid=eastmoney_secid(code), limit=limit), timeout=4)
        data = json.loads(text).get("data") or {}
    except Exception:
        return pd.DataFrame()
    rows = []
    for item in data.get("klines") or []:
        fields = item.split(",")
        if len(fields) < 11:
            continue
        try:
            rows.append(
                {
                    "日期": fields[0],
                    "开盘": float(fields[1]),
                    "收盘": float(fields[2]),
                    "最高": float(fields[3]),
                    "最低": float(fields[4]),
                    "成交量": float(fields[5]),
                    "成交额": float(fields[6]),
                    "振幅%": float(fields[7]),
                    "涨跌幅%": float(fields[8]),
                    "涨跌额": float(fields[9]),
                    "换手%": float(fields[10]),
                }
            )
        except ValueError:
            continue
    return pd.DataFrame(rows)


def _last_value(series: pd.Series, default: float = 0.0) -> float:
    if series.empty or pd.isna(series.iloc[-1]):
        return default
    return float(series.iloc[-1])


def calculate_indicator_row(code: str) -> dict[str, object]:
    kline = fetch_kline(code)
    base = {
        "代码": code,
        "MA5": None,
        "MA10": None,
        "MA20": None,
        "MA60": None,
        "MACD信号": "数据等待",
        "MACD柱": None,
        "KDJ信号": "数据等待",
        "RSI14": None,
        "BOLL位置": "数据等待",
        "量能比": None,
        "均线结构": "数据等待",
        "技术评分": 50,
        "技术结论": "等待日K数据",
    }
    if len(kline) < 35:
        return base

    close = kline["收盘"]
    high = kline["最高"]
    low = kline["最低"]
    volume = kline["成交量"]
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    diff = ema12 - ema26
    dea = diff.ewm(span=9, adjust=False).mean()
    macd_bar = (diff - dea) * 2
    macd_signal = "MACD观察"
    if len(diff) >= 2 and diff.iloc[-2] <= dea.iloc[-2] and diff.iloc[-1] > dea.iloc[-1]:
        macd_signal = "MACD金叉"
    elif len(diff) >= 2 and diff.iloc[-2] >= dea.iloc[-2] and diff.iloc[-1] < dea.iloc[-1]:
        macd_signal = "MACD死叉"
    elif diff.iloc[-1] > dea.iloc[-1] and macd_bar.iloc[-1] > 0:
        macd_signal = "多头延续"
    elif diff.iloc[-1] < dea.iloc[-1] and macd_bar.iloc[-1] < 0:
        macd_signal = "空头延续"

    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, math.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    kdj_signal = "KDJ观察"
    if len(k) >= 2 and k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
        kdj_signal = "KDJ金叉"
    elif len(k) >= 2 and k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
        kdj_signal = "KDJ死叉"
    elif j.iloc[-1] >= 90:
        kdj_signal = "KDJ高位"
    elif j.iloc[-1] <= 15:
        kdj_signal = "KDJ低位"

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi14 = 100 - 100 / (1 + gain / loss.replace(0, math.nan))

    boll_mid = ma20
    boll_std = close.rolling(20).std()
    boll_up = boll_mid + 2 * boll_std
    boll_low = boll_mid - 2 * boll_std
    last_close = _last_value(close)
    boll_pos = (last_close - _last_value(boll_low, last_close)) / max(_last_value(boll_up, last_close) - _last_value(boll_low, last_close), 0.01)
    if boll_pos >= 0.85:
        boll_state = "上轨附近"
    elif boll_pos >= 0.55:
        boll_state = "中上轨"
    elif boll_pos >= 0.30:
        boll_state = "中下轨"
    else:
        boll_state = "下轨修复"

    vol_ratio = _last_value(volume) / max(_last_value(volume.rolling(5).mean()), 1)
    ma_values = {
        "MA5": _last_value(ma5),
        "MA10": _last_value(ma10),
        "MA20": _last_value(ma20),
        "MA60": _last_value(ma60),
    }
    if ma_values["MA5"] > ma_values["MA10"] > ma_values["MA20"] and last_close >= ma_values["MA20"]:
        ma_state = "多头排列"
    elif last_close >= ma_values["MA5"] >= ma_values["MA10"]:
        ma_state = "短线转强"
    elif last_close < ma_values["MA20"]:
        ma_state = "均线下方"
    else:
        ma_state = "震荡修复"

    score = 50
    score += 14 if macd_signal in ("MACD金叉", "多头延续") else -12 if macd_signal in ("MACD死叉", "空头延续") else 0
    score += 12 if kdj_signal == "KDJ金叉" else -10 if kdj_signal == "KDJ死叉" else 0
    score += 14 if ma_state == "多头排列" else 8 if ma_state == "短线转强" else -10 if ma_state == "均线下方" else 2
    score += 8 if 45 <= _last_value(rsi14, 50) <= 68 else -7 if _last_value(rsi14, 50) >= 78 else 4 if _last_value(rsi14, 50) < 35 else 0
    score += 8 if 1.15 <= vol_ratio <= 2.8 else -6 if vol_ratio > 4.0 else 0
    score = int(max(0, min(100, score)))
    if score >= 76:
        conclusion = "强观察"
    elif score >= 62:
        conclusion = "可观察"
    elif score >= 45:
        conclusion = "等待确认"
    else:
        conclusion = "风险优先"

    return {
        **base,
        **ma_values,
        "MACD信号": macd_signal,
        "MACD柱": _last_value(macd_bar),
        "KDJ信号": kdj_signal,
        "RSI14": _last_value(rsi14, 50),
        "BOLL位置": boll_state,
        "量能比": vol_ratio,
        "均线结构": ma_state,
        "技术评分": score,
        "技术结论": conclusion,
    }


@st.cache_data(ttl=1800)
def get_indicators(codes: tuple[str, ...]) -> pd.DataFrame:
    unique_codes = sorted(set(codes))
    if not unique_codes:
        return pd.DataFrame()
    workers = min(8, len(unique_codes))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(calculate_indicator_row, unique_codes))
    return pd.DataFrame(rows)


@st.cache_data(ttl=20)
def fetch_indices() -> pd.DataFrame:
    names = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300"]
    codes = ["sh000001", "sz399001", "sz399006", "sh000688", "sz399300"]
    try:
        text = fetch_url(SINA_INDEX_URL, "gbk")
    except Exception:
        return pd.DataFrame()
    rows = []
    for code, default_name in zip(codes, names):
        match = re.search(rf"hq_str_{code}=\"([^\"]*)\"", text)
        if not match:
            continue
        fields = match.group(1).split(",")
        if len(fields) < 5:
            continue
        name = fields[0] or default_name
        prev_close = parse_float(fields[2])
        current = parse_float(fields[3])
        change = current - prev_close if prev_close else 0.0
        pct = change / prev_close * 100 if prev_close else 0.0
        rows.append({"指数": name, "最新": current, "涨跌": change, "涨跌幅%": pct, "时间": fields[-3] if len(fields) > 3 else ""})
    return pd.DataFrame(rows)


def cn_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}"


def stage_from_row(row: pd.Series) -> str:
    pct = float(row["涨跌幅%"])
    avg = row.get("均价")
    price = float(row["最新价"])
    high = float(row["日高"])
    low = float(row["日低"])
    near_high = high > 0 and price >= high * 0.985
    if pct >= 7 and near_high:
        return "强势高位"
    if pd.notna(avg) and avg and price >= float(avg) and pct > 0:
        return "均线上方"
    if pd.notna(avg) and avg and price < float(avg) and pct > 0:
        return "冲高回落"
    if pct <= -3:
        return "偏弱"
    if low > 0 and (price - low) / max(high - low, 0.01) > 0.65:
        return "修复中"
    return "观察"


def sector_rotation(quotes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if quotes.empty:
        return pd.DataFrame()
    for sector, codes in SECTORS.items():
        part = quotes[quotes["代码"].isin(codes)].copy()
        if part.empty:
            continue
        avg_pct = part["涨跌幅%"].mean()
        strong_count = int((part["涨跌幅%"] >= 3).sum())
        weak_count = int((part["涨跌幅%"] <= -2).sum())
        amount = part["成交额"].fillna(0).sum()
        above_avg = 0
        usable_avg = 0
        for _, row in part.iterrows():
            avg = row.get("均价")
            if pd.notna(avg) and avg:
                usable_avg += 1
                above_avg += int(row["最新价"] >= avg)
        fan_score = avg_pct * 8 + strong_count * 6 - weak_count * 5 + (above_avg / usable_avg * 20 if usable_avg else 0) + math.log10(amount + 1)
        if avg_pct >= 5:
            status = "加速/高潮"
        elif avg_pct >= 2:
            status = "启动"
        elif avg_pct >= 0:
            status = "修复/潜伏"
        elif avg_pct <= -3:
            status = "退潮"
        else:
            status = "分歧"
        rows.append(
            {
                "板块叶片": sector,
                "状态": status,
                "风扇分": fan_score,
                "平均涨跌幅%": avg_pct,
                "强势数": strong_count,
                "偏弱数": weak_count,
                "站均价": f"{above_avg}/{usable_avg}" if usable_avg else "-",
                "成交额": amount,
                "代表股": "、".join(part["名称"].astype(str).tolist()),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("风扇分", ascending=False)


def digest_text(indices: pd.DataFrame, quotes: pd.DataFrame, positions: pd.DataFrame, rotation: pd.DataFrame) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"每日A股动态合集 - {now}", "以下内容不构成个性化投资建议。", ""]
    if not indices.empty:
        idx = "；".join(f"{r['指数']} {r['最新']:.2f}({r['涨跌幅%']:+.2f}%)" for _, r in indices.iterrows())
        lines += ["市场温度", idx, ""]
    if not rotation.empty:
        top = rotation.head(3)
        lines.append("风扇叶片")
        for _, row in top.iterrows():
            lines.append(f"- {row['板块叶片']}：{row['状态']}，平均 {row['平均涨跌幅%']:+.2f}%，代表股：{row['代表股']}")
        lines.append("")
    if not positions.empty and not quotes.empty:
        merged = quotes.merge(positions, on="代码", how="inner")
        if not merged.empty:
            lines.append("持仓检查")
            for _, row in merged.iterrows():
                pnl = (row["最新价"] - row["成本"]) * row["股数"]
                lines.append(f"- {row['名称']} {row['代码']}：最新 {row['最新价']:.2f}，成本 {row['成本']:.3f}，浮盈亏 {pnl:+.2f} 元，状态 {stage_from_row(row)}")
            lines.append("")
    if not quotes.empty:
        watch = quotes.copy()
        watch["状态"] = watch.apply(stage_from_row, axis=1)
        watch = watch[(watch["涨跌幅%"].between(-4.5, 6.5)) & (watch["一手资金"] <= 7000)].sort_values("涨跌幅%", ascending=False)
        lines.append("观察清单")
        for _, row in watch.head(6).iterrows():
            lines.append(f"- {row['名称']} {row['代码']}：{row['最新价']:.2f}，{row['涨跌幅%']:+.2f}%，一手约 {row['一手资金']:.0f} 元，{row['状态']}")
        if "技术评分" in quotes.columns:
            lines += ["", "技术指标摘要"]
            tech = quotes.sort_values("技术评分", ascending=False).head(6)
            for _, row in tech.iterrows():
                rsi_value = row.get("RSI14", 0)
                rsi_text = f"{float(rsi_value):.0f}" if pd.notna(rsi_value) else "-"
                lines.append(
                    f"- {row['名称']} {row['代码']}：评分 {int(row['技术评分'])}，"
                    f"{row['MACD信号']}，{row['KDJ信号']}，{row['均线结构']}，RSI {rsi_text}"
                )
    return "\n".join(lines)


def inject_design() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg: #f5f6f8;
          --surface: #ffffff;
          --surface-2: #f8fafc;
          --ink: #111827;
          --muted: #6b7280;
          --soft: #9ca3af;
          --line: #e5e7eb;
          --line-strong: #d1d5db;
          --red: #b42318;
          --green: #067647;
          --amber: #b54708;
          --blue: #175cd3;
        }
        html, body, [data-testid="stAppViewContainer"] { background: var(--bg); }
        .block-container {
          padding-top: 1.1rem;
          padding-bottom: 2.2rem;
          max-width: 1500px;
        }
        section[data-testid="stSidebar"] {
          background: #eef1f5;
          border-right: 1px solid var(--line-strong);
        }
        section[data-testid="stSidebar"] > div {
          padding-top: 1.1rem;
        }
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
          font-size: 20px;
        }
        section[data-testid="stSidebar"] label {
          color: #374151;
          font-size: 13px;
          font-weight: 680;
        }
        section[data-testid="stSidebar"] textarea {
          border-radius: 8px;
          border-color: #e5e7eb;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
          font-size: 13px;
          line-height: 1.45;
        }
        section[data-testid="stSidebar"] input {
          border-radius: 8px;
        }
        section[data-testid="stSidebar"] div[data-testid="stButton"] button {
          border-radius: 8px;
          height: 42px;
          font-weight: 700;
        }
        section[data-testid="stSidebar"] div[data-baseweb="segmented-control"] {
          background: #ffffff;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          padding: 3px;
        }
        .side-card {
          border: 1px solid var(--line);
          background: rgba(255,255,255,.82);
          border-radius: 8px;
          padding: 11px 12px;
          margin: 10px 0 12px 0;
        }
        .side-title {
          font-size: 13px;
          font-weight: 760;
          color: #111827;
          margin-bottom: 4px;
        }
        .side-help {
          font-size: 12px;
          color: #6b7280;
          line-height: 1.45;
        }
        .side-kpis {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 7px;
          margin-top: 8px;
        }
        .side-kpi {
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          padding: 8px;
          background: #f9fafb;
        }
        .side-kpi div:first-child {
          font-size: 11px;
          color: #6b7280;
        }
        .side-kpi div:last-child {
          font-size: 15px;
          font-weight: 760;
          color: #111827;
        }
        h1, h2, h3 { letter-spacing: 0; }
        div[data-testid="stMetric"] {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 10px 12px;
          min-height: 78px;
        }
        .hero {
          border: 1px solid var(--line-strong);
          background: linear-gradient(180deg, #ffffff 0%, #f9fafb 100%);
          border-radius: 8px;
          padding: 16px 18px;
          margin-bottom: 12px;
        }
        .hero-title {
          font-size: 26px;
          font-weight: 760;
          color: var(--ink);
          margin-bottom: 4px;
        }
        .hero-sub {
          color: var(--muted);
          font-size: 14px;
        }
        .strip {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 12px;
        }
        .pill {
          border: 1px solid var(--line);
          border-radius: 999px;
          padding: 5px 10px;
          font-size: 13px;
          background: #f9fafb;
          color: var(--ink);
        }
        .status-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
          margin: 12px 0;
        }
        .status-card {
          border: 1px solid var(--line);
          background: var(--surface);
          border-radius: 8px;
          padding: 12px 14px;
          min-height: 86px;
        }
        .status-label {
          color: var(--muted);
          font-size: 12px;
          margin-bottom: 8px;
        }
        .status-value {
          color: var(--ink);
          font-size: 23px;
          line-height: 1.1;
          font-weight: 760;
        }
        .status-note {
          color: var(--soft);
          font-size: 12px;
          margin-top: 7px;
        }
        .panel {
          border: 1px solid var(--line);
          border-radius: 8px;
          background: var(--surface);
          padding: 14px 16px;
          margin-bottom: 12px;
        }
        .panel h3 {
          font-size: 16px;
          margin: 0 0 8px 0;
        }
        .signal {
          display: grid;
          grid-template-columns: 92px 1fr;
          gap: 10px;
          border-top: 1px solid var(--line);
          padding: 10px 0;
        }
        .signal:first-of-type { border-top: 0; }
        .tech-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 10px;
          margin-bottom: 12px;
        }
        .tech-card {
          border: 1px solid var(--line);
          background: var(--surface);
          border-radius: 8px;
          padding: 12px;
        }
        .tech-head {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          align-items: flex-start;
          margin-bottom: 10px;
        }
        .tech-name {
          font-weight: 760;
          color: var(--ink);
          font-size: 15px;
        }
        .tech-code {
          color: var(--muted);
          font-size: 12px;
          margin-top: 2px;
        }
        .score {
          width: 42px;
          height: 42px;
          border-radius: 50%;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border: 1px solid var(--line-strong);
          font-weight: 780;
          background: #f8fafc;
        }
        .score-hot { color: var(--green); border-color: #a7f3d0; background: #f0fdf4; }
        .score-mid { color: var(--blue); border-color: #bfdbfe; background: #eff6ff; }
        .score-wait { color: var(--amber); border-color: #fed7aa; background: #fff7ed; }
        .score-risk { color: var(--red); border-color: #fecaca; background: #fff5f5; }
        .mini-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 6px;
        }
        .mini-cell {
          border: 1px solid var(--line);
          background: var(--surface-2);
          border-radius: 7px;
          padding: 7px 8px;
          min-height: 46px;
        }
        .mini-cell div:first-child {
          font-size: 11px;
          color: var(--muted);
        }
        .mini-cell div:last-child {
          font-size: 13px;
          color: var(--ink);
          font-weight: 680;
          margin-top: 3px;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          height: 26px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 680;
          border: 1px solid var(--line);
        }
        .badge-red { color: var(--red); background: #fff5f5; border-color: #fecaca; }
        .badge-green { color: var(--green); background: #f0fdf4; border-color: #bbf7d0; }
        .badge-amber { color: var(--amber); background: #fffbeb; border-color: #fde68a; }
        .badge-blue { color: var(--blue); background: #eff6ff; border-color: #bfdbfe; }
        .muted { color: var(--muted); }
        .compact-table div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
        @media (max-width: 900px) {
          .status-grid, .tech-grid { grid-template-columns: 1fr; }
          .signal { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def market_phase(now: dt.datetime) -> str:
    t = now.time()
    if t < dt.time(9, 15):
        return "盘前准备"
    if t < dt.time(9, 30):
        return "集合竞价"
    if t < dt.time(10, 30):
        return "早盘确认"
    if t < dt.time(11, 30):
        return "早盘后段"
    if t < dt.time(13, 0):
        return "午间复盘"
    if t < dt.time(14, 30):
        return "午后观察"
    if t < dt.time(15, 0):
        return "尾盘决策"
    return "收盘复盘"


def index_temperature(indices: pd.DataFrame) -> tuple[str, str]:
    if indices.empty:
        return "数据等待", "指数源暂不可用，先看个股和板块。"
    avg = indices["涨跌幅%"].mean()
    strong = int((indices["涨跌幅%"] > 0).sum())
    if avg >= 0.7 and strong >= 3:
        return "热", "指数共振偏强，观察强势板块能否扩散。"
    if avg >= 0 and strong >= 2:
        return "温", "指数分化但不弱，优先看主动资金方向。"
    if avg > -0.7:
        return "凉", "指数偏弱震荡，追高容错下降。"
    return "冷", "指数压力较大，先控制仓位和失效线。"


def merge_positions(quotes: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()
    merged = quotes.copy()
    if not positions.empty:
        merged = merged.merge(positions, on="代码", how="left")
        merged["浮盈亏"] = (merged["最新价"] - merged["成本"]) * merged["股数"]
        merged["浮盈亏%"] = (merged["最新价"] / merged["成本"] - 1) * 100
    return merged


def make_watchlist(quotes: pd.DataFrame, cash: int, max_pct: float = 7.0) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()
    watch = quotes[(quotes["一手资金"] <= cash) & (quotes["涨跌幅%"].between(-5, max_pct))].copy()
    if watch.empty:
        return watch
    watch["日内位置%"] = ((watch["最新价"] - watch["日低"]) / (watch["日高"] - watch["日低"]).replace(0, 0.01) * 100).clip(0, 100)
    watch["观察理由"] = watch.apply(
        lambda r: "站均价修复" if r["状态"] == "均线上方" else ("低位拉回" if r["状态"] == "修复中" else r["状态"]),
        axis=1,
    )
    sort_cols = ["涨跌幅%", "成交额"]
    ascending = [False, False]
    if "技术评分" in watch.columns:
        sort_cols = ["技术评分", "涨跌幅%", "成交额"]
        ascending = [False, False, False]
    return watch.sort_values(sort_cols, ascending=ascending)


def build_signals(quotes: pd.DataFrame, positions: pd.DataFrame, rotation: pd.DataFrame, cash: int) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    merged = merge_positions(quotes, positions)
    owned = merged[merged.get("股数", pd.Series(index=merged.index)).notna()] if "股数" in merged else pd.DataFrame()
    for _, row in owned.iterrows():
        cost = float(row["成本"])
        price = float(row["最新价"])
        avg = row.get("均价")
        pct_to_cost = (price / cost - 1) * 100 if cost else 0
        if price >= cost and pct_to_cost >= 1:
            kind, badge = "持仓转强", "badge-green"
            text = f"{row['名称']} 站上成本 {cost:.3f}，浮盈 {pct_to_cost:+.2f}%，观察能否维持均线上方。"
        elif avg and pd.notna(avg) and price < float(avg) and price < cost:
            kind, badge = "持仓风险", "badge-red"
            text = f"{row['名称']} 低于成本和均价，先看能否收回 {float(avg):.2f}；失效看日低 {row['日低']:.2f}。"
        elif price < cost:
            kind, badge = "持仓观察", "badge-amber"
            text = f"{row['名称']} 仍低于成本 {cost:.3f}，但未明显破坏，观察成本线能否收复。"
        else:
            kind, badge = "持仓稳定", "badge-blue"
            text = f"{row['名称']} 贴近成本线，按分时均价和日内高低判断强弱。"
        signals.append({"kind": kind, "badge": badge, "text": text})

    if not rotation.empty:
        top = rotation.iloc[0]
        signals.append(
            {
                "kind": "主线叶片",
                "badge": "badge-green" if top["状态"] in ("启动", "加速/高潮") else "badge-blue",
                "text": f"{top['板块叶片']} 当前风扇分最高，状态 {top['状态']}；若代表股继续站均价，资金仍在这片叶片上。",
            }
        )
        crowded = rotation[rotation["状态"].eq("加速/高潮")]
        if not crowded.empty:
            row = crowded.iloc[0]
            signals.append(
                {
                    "kind": "拥挤提醒",
                    "badge": "badge-amber",
                    "text": f"{row['板块叶片']} 已进入加速/高潮，适合看强度，不适合把低吸逻辑变成追高。",
            }
        )

    if "技术评分" in quotes.columns:
        tech = quotes.sort_values(["技术评分", "涨跌幅%"], ascending=[False, False]).head(3)
        for _, row in tech.iterrows():
            if int(row["技术评分"]) >= 68:
                signals.append(
                    {
                        "kind": "技术共振",
                        "badge": "badge-green",
                        "text": f"{row['名称']} {row['代码']} 技术评分 {int(row['技术评分'])}，{row['MACD信号']}、{row['KDJ信号']}、{row['均线结构']}，适合放进重点观察窗口。",
                    }
                )
                break

    watch = make_watchlist(quotes, cash)
    if not watch.empty:
        row = watch.iloc[0]
        signals.append(
            {
                "kind": "观察窗口",
                "badge": "badge-blue",
                "text": f"{row['名称']} {row['代码']} 在资金上限内，一手约 {row['一手资金']:.0f} 元，状态 {row['状态']}，下一步看日高 {row['日高']:.2f} 与均价。",
            }
        )
    return signals[:8]


def render_status_cards(items: list[tuple[str, str, str]]) -> None:
    html_parts = ['<div class="status-grid">']
    for label, value, note in items:
        html_parts.append(
            f'<div class="status-card">'
            f'<div class="status-label">{html.escape(label)}</div>'
            f'<div class="status-value">{html.escape(value)}</div>'
            f'<div class="status-note">{html.escape(note)}</div>'
            f"</div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def score_class(score: int) -> str:
    if score >= 76:
        return "score-hot"
    if score >= 62:
        return "score-mid"
    if score >= 45:
        return "score-wait"
    return "score-risk"


def render_tech_matrix(quotes: pd.DataFrame) -> None:
    if quotes.empty or "技术评分" not in quotes.columns:
        st.info("暂无技术指标数据。")
        return
    focus = quotes.sort_values(["技术评分", "涨跌幅%"], ascending=[False, False]).head(6)
    html_parts = ['<div class="tech-grid">']
    for _, row in focus.iterrows():
        score = int(row.get("技术评分", 50))
        rsi_value = row.get("RSI14", 0)
        rsi_text = f"{float(rsi_value):.0f}" if pd.notna(rsi_value) else "-"
        vol_value = row.get("量能比", 0)
        vol_text = f"{float(vol_value):.2f}" if pd.notna(vol_value) else "-"
        html_parts.append(
            f'<div class="tech-card">'
            f'<div class="tech-head">'
            f'<div><div class="tech-name">{html.escape(str(row["名称"]))}</div>'
            f'<div class="tech-code">{html.escape(str(row["代码"]))}　{row["最新价"]:.2f}　{row["涨跌幅%"]:+.2f}%</div></div>'
            f'<div class="score {score_class(score)}">{score}</div>'
            f"</div>"
            f'<div class="mini-grid">'
            f'<div class="mini-cell"><div>MACD</div><div>{html.escape(str(row.get("MACD信号", "-")))}</div></div>'
            f'<div class="mini-cell"><div>KDJ</div><div>{html.escape(str(row.get("KDJ信号", "-")))}</div></div>'
            f'<div class="mini-cell"><div>均线</div><div>{html.escape(str(row.get("均线结构", "-")))}</div></div>'
            f'<div class="mini-cell"><div>RSI / BOLL</div><div>{rsi_text} / {html.escape(str(row.get("BOLL位置", "-")))}</div></div>'
            f'<div class="mini-cell"><div>量能比</div><div>{vol_text}</div></div>'
            f'<div class="mini-cell"><div>结论</div><div>{html.escape(str(row.get("技术结论", "-")))}</div></div>'
            f"</div></div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_signals(signals: list[dict[str, str]]) -> None:
    if not signals:
        st.info("暂无信号，等待行情源刷新。")
        return
    html = ['<div class="panel"><h3>交易员信号队列</h3>']
    for item in signals:
        html.append(
            f'<div class="signal"><div><span class="badge {item["badge"]}">{item["kind"]}</span></div>'
            f'<div>{item["text"]}</div></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_observation_windows(quotes: pd.DataFrame, positions: pd.DataFrame, rotation: pd.DataFrame) -> None:
    owned = merge_positions(quotes, positions)
    owned = owned[owned.get("股数", pd.Series(index=owned.index)).notna()] if "股数" in owned else pd.DataFrame()
    top_sector = rotation.iloc[0]["板块叶片"] if not rotation.empty else "等待板块确认"
    weak_sector = rotation.iloc[-1]["板块叶片"] if not rotation.empty else "等待板块确认"
    hold_lines = []
    for _, row in owned.iterrows():
        hold_lines.append(f"{row['名称']}：成本 {row['成本']:.3f}，均价 {row['均价'] if pd.notna(row.get('均价')) else '-'}，日低 {row['日低']:.2f}")
    hold_text = "<br>".join(hold_lines) if hold_lines else "暂无持仓输入"
    st.markdown(
        f"""
        <div class="panel">
          <h3>观察窗口</h3>
          <div class="strip">
            <span class="pill">早盘：确认指数强弱与第一主线</span>
            <span class="pill">午盘：看持仓是否站回均价/成本</span>
            <span class="pill">尾盘：只按确认信号处理，不猜明天</span>
          </div>
          <div style="margin-top:12px" class="muted">当前强叶片：{top_sector}；弱叶片：{weak_sector}</div>
          <div style="margin-top:8px" class="muted">持仓关键线：{hold_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_card(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="side-card">
          <div class="side-title">{title}</div>
          <div class="side-help">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="A股每日动态合集", page_icon="📊", layout="wide")
    inject_design()

    with st.sidebar:
        st.markdown("## 工作台")
        render_sidebar_card("交易设置", "盘中看承接与均价，复盘看主线持续性，低吸观察只筛修复不追高。")
        mode = st.segmented_control("模式", ["盘中", "复盘", "低吸观察"], default="盘中", label_visibility="collapsed")
        c_cash, c_pct = st.columns([1.05, 0.95])
        with c_cash:
            cash = st.number_input("一手资金上限", min_value=500, value=7000, step=500)
        with c_pct:
            max_watch_pct = st.number_input("观察涨幅上限", min_value=3.0, max_value=12.0, value=7.0, step=0.5, format="%.1f")
        max_watch_pct = st.slider("观察涨幅上限辅助滑杆", 3.0, 12.0, max_watch_pct, 0.5, label_visibility="collapsed")

        st.markdown(
            f"""
            <div class="side-kpis">
              <div class="side-kpi"><div>一手资金</div><div>{int(cash)} 元</div></div>
              <div class="side-kpi"><div>追高过滤</div><div>{max_watch_pct:.1f}%</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_sidebar_card("股票池", "只填 6 位代码，空格或换行都可以。建议只放真正会看的票，列表越干净越像交易台。")
        codes_text = st.text_area("自选池", DEFAULT_CODES, height=128, label_visibility="collapsed", placeholder="600487 000758 000733\n603678 000636 600522")
        code_count = len(set(parse_codes(codes_text)))
        st.caption(f"已识别 {code_count} 只自选股")

        render_sidebar_card("持仓账本", "每行：代码 股数 成本。这里只用于风险线和浮盈亏观察，不会连接券商下单。")
        positions_text = st.text_area("持仓", DEFAULT_POSITIONS, height=92, label_visibility="collapsed", placeholder="600487 200 68.62\n002491 100 22.05")
        pos_count = len(parse_positions(positions_text))
        st.caption(f"已识别 {pos_count} 条持仓")

        render_sidebar_card("指标引擎", "已启用 MACD、KDJ、RSI、BOLL、MA5/10/20/60、量能比和技术评分。评分只做观察，不替代纪律线。")

        if st.button("刷新行情", width="stretch"):
            st.cache_data.clear()

    codes = set(parse_codes(codes_text))
    positions = parse_positions(positions_text)
    if not positions.empty:
        codes.update(positions["代码"].tolist())
    for group in SECTORS.values():
        codes.update(group)

    indices = fetch_indices()
    quotes = get_quotes(tuple(codes))
    now_dt = dt.datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    phase = market_phase(now_dt)
    temp, temp_note = index_temperature(indices)

    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-title">A股每日动态合集</div>
          <div class="hero-sub">更新时间：{now}　市场阶段：{phase}　模式：{mode}　以下内容不构成个性化投资建议</div>
          <div class="strip">
            <span class="pill">市场温度：{temp}</span>
            <span class="pill">{temp_note}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not indices.empty:
        cols = st.columns(len(indices))
        for col, (_, row) in zip(cols, indices.iterrows()):
            col.metric(row["指数"], f"{row['最新']:.2f}", f"{row['涨跌幅%']:+.2f}%")

    if quotes.empty:
        st.warning("暂未获取到个股行情，请稍后刷新。")
        return

    indicators = get_indicators(tuple(quotes["代码"].tolist()))
    if not indicators.empty:
        quotes = quotes.merge(indicators, on="代码", how="left")
    quotes["状态"] = quotes.apply(stage_from_row, axis=1)
    rotation = sector_rotation(quotes)
    merged = merge_positions(quotes, positions)
    owned = merged[merged.get("股数", pd.Series(index=merged.index)).notna()] if "股数" in merged else pd.DataFrame()
    signals = build_signals(quotes, positions, rotation, int(cash))

    top_sector = rotation.head(1)["板块叶片"].iloc[0] if not rotation.empty else "-"
    strong_count = int((quotes["涨跌幅%"] >= 5).sum())
    red_count = int((quotes["涨跌幅%"] > 0).sum())
    pnl_total = owned["浮盈亏"].sum() if not owned.empty and "浮盈亏" in owned else 0.0
    tech_avg = quotes["技术评分"].mean() if "技术评分" in quotes.columns else 0
    render_status_cards(
        [
            ("主线叶片", str(top_sector), "资金当前最集中的板块"),
            ("红盘自选", f"{red_count}/{len(quotes)}", "自选池上涨家数"),
            ("强势股数", str(strong_count), "涨幅超过 5% 的观察票"),
            ("技术均分", f"{tech_avg:.0f}", f"持仓浮盈亏 {pnl_total:+.2f} 元"),
        ]
    )

    left, right = st.columns([1.12, 0.88])
    with left:
        render_signals(signals)
    with right:
        render_observation_windows(quotes, positions, rotation)

    render_tech_matrix(quotes)

    tab_digest, tab_tech, tab_hold, tab_rotation, tab_watch, tab_text = st.tabs(["盘面总览", "技术指标", "持仓雷达", "风扇蜂巢", "观察池", "文本合集"])

    with tab_digest:
        st.subheader("主线排序")
        if rotation.empty:
            st.info("暂无板块轮动数据。")
        else:
            summary = rotation.head(6).copy()
            summary["成交额"] = summary["成交额"].map(cn_money)
            st.dataframe(summary, width="stretch", hide_index=True)
        st.subheader("自选强弱分布")
        rank = quotes[["代码", "名称", "最新价", "涨跌幅%", "状态", "一手资金", "成交额", "换手%", "日高", "日低"]].copy()
        rank["成交额"] = rank["成交额"].map(cn_money)
        st.dataframe(rank.sort_values("涨跌幅%", ascending=False), width="stretch", hide_index=True)

    with tab_tech:
        tech_cols = [
            "代码",
            "名称",
            "最新价",
            "涨跌幅%",
            "技术评分",
            "技术结论",
            "MACD信号",
            "MACD柱",
            "KDJ信号",
            "RSI14",
            "BOLL位置",
            "量能比",
            "均线结构",
            "MA5",
            "MA10",
            "MA20",
            "MA60",
        ]
        available_cols = [col for col in tech_cols if col in quotes.columns]
        st.dataframe(quotes[available_cols].sort_values("技术评分", ascending=False), width="stretch", hide_index=True)
        st.caption("技术评分用于观察强弱共振，不代表确定性买卖点。MACD/KDJ 金叉需要结合位置、量能和板块主线确认。")

    with tab_hold:
        if owned.empty:
            st.info("左侧输入持仓后，这里会显示成本线、浮盈亏和风险状态。")
        else:
            hold = owned.copy()
            hold["成本距离%"] = (hold["最新价"] / hold["成本"] - 1) * 100
            hold["日内位置%"] = ((hold["最新价"] - hold["日低"]) / (hold["日高"] - hold["日低"]).replace(0, 0.01) * 100).clip(0, 100)
            st.dataframe(
                hold[["代码", "名称", "股数", "成本", "最新价", "成本距离%", "浮盈亏", "浮盈亏%", "状态", "均价", "日高", "日低"]],
                width="stretch",
                hide_index=True,
            )
            for _, row in hold.iterrows():
                st.progress(float(row["日内位置%"]) / 100, text=f"{row['名称']} 日内位置 {row['日内位置%']:.0f}% | 成本距离 {row['成本距离%']:+.2f}%")

    with tab_rotation:
        show = rotation.copy()
        if not show.empty:
            show["成交额"] = show["成交额"].map(cn_money)
            st.dataframe(show, width="stretch", hide_index=True)
            st.bar_chart(rotation.set_index("板块叶片")["风扇分"])
            honey = rotation[["板块叶片", "状态", "风扇分", "代表股"]].copy()
            honey["蜂蜜甜度"] = honey["风扇分"].rank(pct=True) * 100
            honey["资金判断"] = honey["状态"].map({"加速/高潮": "甜但拥挤", "启动": "资金主动流入", "修复/潜伏": "等待确认", "分歧": "换手分歧", "退潮": "资金撤退"}).fillna("观察")
            st.subheader("蜂巢资金迁徙")
            st.dataframe(honey.sort_values("蜂蜜甜度", ascending=False), width="stretch", hide_index=True)

    with tab_watch:
        watch = make_watchlist(quotes, int(cash), max_watch_pct)
        if watch.empty:
            st.warning("当前没有符合资金和涨幅过滤的观察票。")
        else:
            watch_show = watch[["代码", "名称", "最新价", "涨跌幅%", "状态", "观察理由", "一手资金", "成交额", "换手%", "日内位置%", "日高", "日低"]].copy()
            watch_show["成交额"] = watch_show["成交额"].map(cn_money)
            st.dataframe(watch_show, width="stretch", hide_index=True)
            st.subheader("下一步确认")
            for _, row in watch.head(5).iterrows():
                st.markdown(f"- **{row['名称']} {row['代码']}**：看 `{row['日高']:.2f}` 是否突破，看 `{row['日低']:.2f}` 是否失守。")

    with tab_text:
        st.text_area("可复制文本", digest_text(indices, quotes, positions, rotation), height=520)


if __name__ == "__main__":
    main()
