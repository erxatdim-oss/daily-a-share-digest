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
import os
import re
import subprocess
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

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
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{limit},qfq"
SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006,sh000688,sz399300"
EASTMONEY_INDEX_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&invt=2&fields=f14,f12,f2,f3&secids=1.000001,0.399001,0.399006,1.000688,0.399300"
)
DEFAULT_REFERENCE_URL = "https://npcs1983.top"
TRADE_LOG_PATH = os.path.expanduser("~/.a_share_daily_digest/trade_log.csv")
CN_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_CODES = ""
DEFAULT_POSITIONS = ""

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


def compact_text(value: object, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def normalize_reference_url(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw if re.match(r"^https?://", raw) else f"https://{raw}")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_json_url(url: str, timeout: float = 5) -> dict[str, object]:
    try:
        return json.loads(fetch_url(url, timeout=timeout))
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["/usr/bin/curl", "-L", "-s", "--max-time", str(max(1, int(math.ceil(timeout)))), url],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except Exception:
        return {}
    return {}


def fetch_reference_endpoint(base_url: str, endpoint: str, timeout: float) -> dict[str, object]:
    if not base_url:
        return {}
    return fetch_json_url(f"{base_url}{endpoint}", timeout=timeout)


@st.cache_data(ttl=45)
def fetch_reference_bundle(base_url: str, enabled: bool) -> dict[str, object]:
    base = normalize_reference_url(base_url)
    if not enabled or not base:
        return {}
    endpoints = {
        "status": ("/api/market/status", 4.0),
        "indices": ("/api/market/indices", 4.0),
        "main_flow": ("/api/main-fund-flow?limit=8", 5.0),
    }
    result: dict[str, object] = {"base_url": base, "ok": False}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(endpoints))
    futures = {
        executor.submit(fetch_reference_endpoint, base, endpoint, timeout): key
        for key, (endpoint, timeout) in endpoints.items()
    }
    try:
        for future in concurrent.futures.as_completed(futures, timeout=7):
            key = futures[future]
            try:
                payload = future.result(timeout=0.1)
            except Exception:
                payload = {}
            result[key] = payload
            if payload:
                result["ok"] = True
    except concurrent.futures.TimeoutError:
        pass
    finally:
        for future, key in futures.items():
            if key in result:
                continue
            if future.done():
                try:
                    payload = future.result(timeout=0.1)
                except Exception:
                    payload = {}
                result[key] = payload
                if payload:
                    result["ok"] = True
            else:
                future.cancel()
                result[key] = {}
        executor.shutdown(wait=False, cancel_futures=True)
    return result


@st.cache_data(ttl=180)
def fetch_reference_report_payload(base_url: str, enabled: bool) -> dict[str, object]:
    base = normalize_reference_url(base_url)
    if not enabled or not base:
        return {}
    return fetch_reference_endpoint(base, "/api/report/latest", 8.0)


def reference_status(bundle: dict[str, object]) -> dict[str, object]:
    payload = bundle.get("status") if isinstance(bundle, dict) else {}
    if not isinstance(payload, dict):
        return {}
    status = payload.get("status")
    return status if isinstance(status, dict) else {}


def reference_report(bundle: dict[str, object]) -> dict[str, object]:
    payload = bundle.get("report") if isinstance(bundle, dict) else {}
    if not isinstance(payload, dict):
        return {}
    report = payload.get("report")
    return report if isinstance(report, dict) else {}


def reference_indices_df(bundle: dict[str, object]) -> pd.DataFrame:
    payload = bundle.get("indices") if isinstance(bundle, dict) else {}
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows = []
    for item in payload.get("indices") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "指数": item.get("name") or item.get("code") or "-",
                "最新": parse_float(item.get("price")),
                "涨跌": parse_float(item.get("change_amt")),
                "涨跌幅%": parse_float(item.get("change_pct")),
                "时间": "",
            }
        )
    return pd.DataFrame(rows)


def reference_flow_df(bundle: dict[str, object], side: str = "inflow") -> pd.DataFrame:
    payload = bundle.get("main_flow") if isinstance(bundle, dict) else {}
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows = []
    for item in payload.get(side) or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "排名": item.get("rank"),
                "代码": str(item.get("code") or ""),
                "名称": item.get("name") or "-",
                "最新价": parse_float(item.get("price")),
                "涨跌幅%": parse_float(item.get("change_pct")),
                "主力净额": parse_float(item.get("main_net_amount")),
                "主力净额文本": item.get("main_net_amount_text") or cn_money(parse_float(item.get("main_net_amount"))),
                "净占比": item.get("net_ratio_text") or "",
                "换手率": item.get("turnover_rate_text") or "",
                "来源": item.get("source") or "外部参考",
            }
        )
    return pd.DataFrame(rows)


def reference_sectors_df(bundle: dict[str, object], limit: int = 12) -> pd.DataFrame:
    report = reference_report(bundle)
    sectors = report.get("sectors") or []
    if not sectors and isinstance(report.get("sector_views"), dict):
        today = report["sector_views"].get("today") or {}
        sectors = today.get("sectors") or []
    rows = []
    for item in sectors[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "排名": item.get("rank"),
                "板块": item.get("name") or "-",
                "涨跌幅%": parse_float(item.get("change_pct")),
                "评分": parse_float(item.get("score")),
                "成交额": item.get("amount"),
                "换手率": item.get("turnover_rate"),
                "理由": item.get("reason") or "",
                "对比": (item.get("compare") or {}).get("text") if isinstance(item.get("compare"), dict) else "",
            }
        )
    return pd.DataFrame(rows)


def reference_stocks_df(bundle: dict[str, object], limit: int = 12) -> pd.DataFrame:
    report = reference_report(bundle)
    rows = []
    for item in (report.get("stocks") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "排名": item.get("rank"),
                "代码": str(item.get("code") or item.get("plain_code") or ""),
                "名称": item.get("name") or "-",
                "板块": item.get("sector") or "-",
                "现价": parse_float(item.get("price")),
                "涨跌幅%": parse_float(item.get("change_pct")),
                "评分": parse_float(item.get("rank_score") or item.get("score")),
                "建议": item.get("advice") or item.get("position_hint") or "",
                "风控": item.get("stop_loss") or "",
                "理由": item.get("reason") or "",
            }
        )
    return pd.DataFrame(rows)


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
    rows = []
    try:
        text = fetch_url(EASTMONEY_KLINE_URL.format(secid=eastmoney_secid(code), limit=limit), timeout=6)
        data = json.loads(text).get("data") or {}
    except Exception:
        data = {}
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
    if rows:
        return pd.DataFrame(rows)

    # Fallback: Tencent qfq daily kline
    try:
        symbol = f"{market_prefix(code)}{code}"
        t_text = fetch_url(TENCENT_KLINE_URL.format(symbol=symbol, limit=limit), timeout=6)
        t_data = json.loads(t_text).get("data", {}).get(symbol, {})
    except Exception:
        return pd.DataFrame()
    day_rows = t_data.get("qfqday") or t_data.get("day") or []
    for row in day_rows:
        # [date, open, close, high, low, volume, ...]
        if len(row) < 6:
            continue
        try:
            rows.append(
                {
                    "日期": row[0],
                    "开盘": float(row[1]),
                    "收盘": float(row[2]),
                    "最高": float(row[3]),
                    "最低": float(row[4]),
                    "成交量": float(row[5]),
                    "成交额": 0.0,
                    "振幅%": 0.0,
                    "涨跌幅%": 0.0,
                    "涨跌额": 0.0,
                    "换手%": 0.0,
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
    workers = min(4, len(unique_codes))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(calculate_indicator_row, unique_codes))
    return pd.DataFrame(rows)


def prepare_backtest_kline(code: str, limit: int) -> pd.DataFrame:
    kline = fetch_kline(code, limit)
    if kline.empty:
        return pd.DataFrame()
    df = kline.copy()
    needed = ["日期", "开盘", "收盘", "最高", "最低", "成交量"]
    missing = [col for col in needed if col not in df.columns]
    if missing:
        return pd.DataFrame()
    df = df[needed].copy()
    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.dropna(subset=["日期", "开盘", "收盘", "最高", "最低"]).sort_values("日期")
    df = df.drop_duplicates("日期").tail(limit).reset_index(drop=True)
    return df


def build_backtest_signals(df: pd.DataFrame, strategy: str) -> tuple[pd.Series, pd.Series]:
    close = df["收盘"]
    high = df["最高"]
    low = df["最低"]
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, math.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()

    if strategy == "MA5上穿MA20":
        buy = (ma5.shift(1) <= ma20.shift(1)) & (ma5 > ma20)
        sell = (ma5.shift(1) >= ma20.shift(1)) & (ma5 < ma20)
    elif strategy == "MACD金叉死叉":
        buy = (dif.shift(1) <= dea.shift(1)) & (dif > dea)
        sell = (dif.shift(1) >= dea.shift(1)) & (dif < dea)
    elif strategy == "KDJ低位金叉":
        buy = (k.shift(1) <= d.shift(1)) & (k > d) & (k < 65)
        sell = ((k.shift(1) >= d.shift(1)) & (k < d)) | (k > 85)
    elif strategy == "20日新高突破":
        prev_high20 = high.shift(1).rolling(20).max()
        buy = close > prev_high20
        sell = close < ma10
    else:
        buy = (ma5 > ma20) & (dif > dea) & (dif.shift(1) <= dea.shift(1))
        sell = (close < ma10) | ((dif.shift(1) >= dea.shift(1)) & (dif < dea))
    return buy.fillna(False), sell.fillna(False)


def run_single_backtest(
    code: str,
    name: str,
    strategy: str,
    limit: int,
    initial_cash: float,
    fee_bps: float,
    stamp_tax_pct: float,
    slippage_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    df = prepare_backtest_kline(code, limit)
    if len(df) < 60:
        return (
            {
                "代码": code,
                "名称": name,
                "策略": strategy,
                "样本天数": len(df),
                "总收益%": None,
                "买入持有%": None,
                "超额%": None,
                "最大回撤%": None,
                "交易次数": 0,
                "胜率%": None,
                "结论": "K线不足",
            },
            pd.DataFrame(),
            pd.DataFrame(),
        )

    buy_signal, sell_signal = build_backtest_signals(df, strategy)
    fee_rate = fee_bps / 10000
    stamp_rate = stamp_tax_pct / 100
    slip_rate = slippage_pct / 100
    stop_rate = stop_loss_pct / 100
    take_rate = take_profit_pct / 100
    cash = float(initial_cash)
    shares = 0
    entry_price = 0.0
    entry_date = None
    trades: list[dict[str, object]] = []
    curve = []

    first_close = float(df["收盘"].iloc[0])
    for i in range(1, len(df)):
        today = df.iloc[i]
        prev = df.iloc[i - 1]
        open_price = float(today["开盘"])
        prev_close = float(prev["收盘"])

        if shares > 0:
            stop_hit = prev_close <= entry_price * (1 - stop_rate)
            take_hit = prev_close >= entry_price * (1 + take_rate)
            if bool(sell_signal.iloc[i - 1]) or stop_hit or take_hit:
                reason = "止损" if stop_hit else "止盈" if take_hit else "策略卖出"
                sell_price = open_price * (1 - slip_rate)
                gross = shares * sell_price
                cash += gross * (1 - fee_rate - stamp_rate)
                pnl_pct = (sell_price / entry_price - 1) * 100
                trades.append(
                    {
                        "买入日": entry_date.strftime("%Y-%m-%d") if entry_date is not None else "-",
                        "卖出日": today["日期"].strftime("%Y-%m-%d"),
                        "买入价": entry_price,
                        "卖出价": sell_price,
                        "股数": shares,
                        "收益%": pnl_pct,
                        "卖出原因": reason,
                    }
                )
                shares = 0
                entry_price = 0.0
                entry_date = None

        if shares == 0 and bool(buy_signal.iloc[i - 1]):
            buy_price = open_price * (1 + slip_rate)
            lot = int(cash / (buy_price * (1 + fee_rate)) // 100 * 100)
            if lot >= 100:
                cash -= lot * buy_price * (1 + fee_rate)
                shares = lot
                entry_price = buy_price
                entry_date = today["日期"]

        equity = cash + shares * float(today["收盘"])
        benchmark = initial_cash * float(today["收盘"]) / first_close if first_close else initial_cash
        curve.append({"日期": today["日期"], "资产曲线": equity, "买入持有": benchmark})

    curve_df = pd.DataFrame(curve)
    trades_df = pd.DataFrame(trades)
    final_equity = float(curve_df["资产曲线"].iloc[-1]) if not curve_df.empty else initial_cash
    total_return = (final_equity / initial_cash - 1) * 100
    benchmark_return = (float(df["收盘"].iloc[-1]) / first_close - 1) * 100 if first_close else 0.0
    running_high = curve_df["资产曲线"].cummax() if not curve_df.empty else pd.Series([initial_cash])
    drawdown = curve_df["资产曲线"] / running_high - 1 if not curve_df.empty else pd.Series([0.0])
    max_drawdown = float(drawdown.min() * 100)
    win_rate = float((trades_df["收益%"] > 0).mean() * 100) if not trades_df.empty else None
    if total_return > benchmark_return and max_drawdown > -18:
        conclusion = "跑赢持有"
    elif total_return > 0 and max_drawdown > -25:
        conclusion = "有正收益"
    elif max_drawdown <= -25:
        conclusion = "回撤偏大"
    else:
        conclusion = "策略无优势"

    return (
        {
            "代码": code,
            "名称": name,
            "策略": strategy,
            "样本天数": len(df),
            "总收益%": total_return,
            "买入持有%": benchmark_return,
            "超额%": total_return - benchmark_return,
            "最大回撤%": max_drawdown,
            "交易次数": len(trades_df),
            "胜率%": win_rate,
            "结论": conclusion,
        },
        curve_df,
        trades_df,
    )


@st.cache_data(ttl=20)
def fetch_indices() -> pd.DataFrame:
    names = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300"]
    codes = ["sh000001", "sz399001", "sz399006", "sh000688", "sz399300"]
    try:
        text = fetch_url(SINA_INDEX_URL, "gbk")
    except Exception:
        text = ""
    rows = []
    if text:
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
    if rows:
        return pd.DataFrame(rows)

    # Fallback when Sina index API is blocked or delayed.
    try:
        em_text = fetch_url(EASTMONEY_INDEX_URL)
        em_data = json.loads(em_text).get("data", {}).get("diff", [])
    except Exception:
        return pd.DataFrame()
    for item in em_data:
        name = str(item.get("f14") or "")
        current = parse_float(item.get("f2"))
        pct = parse_float(item.get("f3"))
        change = current * pct / 100 if current else 0.0
        rows.append({"指数": name, "最新": current, "涨跌": change, "涨跌幅%": pct, "时间": ""})
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


def classify_fan_leaf(stage: str, fan_score: float, rank: int, total: int) -> str:
    """Map sector state into simple rotation labels for quick intraday reading."""
    top_half = rank <= max(1, math.ceil(total * 0.5))
    if stage == "加速/高潮":
        return "加速"
    if stage == "启动":
        return "启动"
    if stage == "修复/潜伏":
        return "潜伏" if top_half or fan_score >= 54 else "冷却"
    if stage == "分歧":
        return "退潮" if not top_half else "冷却"
    if stage == "退潮":
        return "退潮"
    return "冷却"


def build_fan_radar(rotation: pd.DataFrame) -> pd.DataFrame:
    if rotation.empty:
        return pd.DataFrame()
    radar = rotation.copy().reset_index(drop=True)
    total = len(radar)
    radar["风叶阶段"] = [
        classify_fan_leaf(str(row["状态"]), float(row["风扇分"]), idx + 1, total)
        for idx, (_, row) in enumerate(radar.iterrows())
    ]
    radar["甜点分"] = (radar["风扇分"].rank(pct=True) * 100).round(0).astype(int)
    return radar


def build_rotation_clock(rotation: pd.DataFrame) -> pd.DataFrame:
    if rotation.empty:
        return pd.DataFrame()
    clock_order = ["加速", "启动", "潜伏", "冷却", "退潮"]
    rows = []
    radar = build_fan_radar(rotation)
    for stage in clock_order:
        names = radar[radar["风叶阶段"] == stage]["板块叶片"].tolist()
        rows.append({"时钟阶段": stage, "板块": "、".join(names) if names else "-"})
    return pd.DataFrame(rows)


def load_trade_log() -> pd.DataFrame:
    cols = ["日期", "代码", "名称", "方向", "价格", "股数", "理由", "结果%", "备注"]
    if not os.path.exists(TRADE_LOG_PATH):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(TRADE_LOG_PATH, dtype={"代码": str})
    except Exception:
        return pd.DataFrame(columns=cols)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    return df[cols]


def append_trade_log(entry: dict[str, object]) -> None:
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    df = load_trade_log()
    df = pd.concat([df, pd.DataFrame([entry])], ignore_index=True)
    df.to_csv(TRADE_LOG_PATH, index=False, encoding="utf-8-sig")


def digest_text(indices: pd.DataFrame, quotes: pd.DataFrame, positions: pd.DataFrame, rotation: pd.DataFrame) -> str:
    now = cn_now().strftime("%Y-%m-%d %H:%M")
    lines = [f"A股短线王 - {now}", "以下内容不构成个性化投资建议。", ""]
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
        .cockpit {
          border: 1px solid var(--line-strong);
          background: #ffffff;
          border-radius: 8px;
          padding: 14px;
          margin: 12px 0;
        }
        .cockpit-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
          padding-bottom: 12px;
          border-bottom: 1px solid var(--line);
          margin-bottom: 12px;
        }
        .cockpit-title {
          font-size: 18px;
          font-weight: 780;
          color: var(--ink);
        }
        .cockpit-sub {
          color: var(--muted);
          font-size: 13px;
          margin-top: 3px;
        }
        .cockpit-grid {
          display: grid;
          grid-template-columns: 1.15fr .85fr .85fr;
          gap: 10px;
        }
        .cockpit-card {
          border: 1px solid var(--line);
          background: #f9fafb;
          border-radius: 8px;
          padding: 12px;
          min-height: 138px;
        }
        .cockpit-card h4 {
          margin: 0 0 8px 0;
          font-size: 14px;
          color: #374151;
        }
        .market-state-main {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
        }
        .market-state-main strong {
          font-size: 22px;
          color: var(--ink);
        }
        .market-prompt {
          color: var(--muted);
          font-size: 13px;
          line-height: 1.55;
        }
        .flow-row, .rank-row {
          display: grid;
          grid-template-columns: 24px minmax(0, 1fr) auto;
          gap: 8px;
          align-items: center;
          border-top: 1px solid var(--line);
          padding: 7px 0;
          font-size: 13px;
        }
        .flow-row:first-of-type, .rank-row:first-of-type { border-top: 0; }
        .rank-no {
          color: var(--soft);
          font-weight: 760;
        }
        .rank-main {
          min-width: 0;
        }
        .rank-main b {
          display: block;
          color: var(--ink);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .rank-main small {
          display: block;
          color: var(--muted);
          font-size: 11px;
        }
        .money-in { color: var(--red); font-weight: 760; }
        .money-out { color: var(--green); font-weight: 760; }
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
          .status-grid, .tech-grid, .cockpit-grid { grid-template-columns: 1fr; }
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


def cn_now() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def trading_day_status(now: dt.datetime) -> str:
    if now.weekday() >= 5:
        return "休市"
    t = now.time()
    if t < dt.time(9, 15):
        return "盘前"
    if dt.time(9, 15) <= t < dt.time(11, 30):
        return "交易中"
    if dt.time(11, 30) <= t < dt.time(13, 0):
        return "午休"
    if dt.time(13, 0) <= t < dt.time(15, 0):
        return "交易中"
    return "收盘后"


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


def make_bottom_watchlist(quotes: pd.DataFrame, cash: int) -> pd.DataFrame:
    """Bottom-fishing observation pool (not buy advice)."""
    if quotes.empty:
        return pd.DataFrame()
    pool = quotes[
        (quotes["一手资金"] <= cash)
        & (quotes["涨跌幅%"].between(-7, 3))
        & (quotes["状态"].isin(["修复中", "均线下方"]))
    ].copy()
    if pool.empty:
        return pool
    if "技术评分" in pool.columns:
        pool = pool[pool["技术评分"] >= 42]
        return pool.sort_values(["技术评分", "涨跌幅%"], ascending=[False, False])
    return pool.sort_values(["涨跌幅%", "成交额"], ascending=[False, False])


def make_entry_watchlist(quotes: pd.DataFrame, cash: int, max_pct: float = 7.0) -> pd.DataFrame:
    """Trend-follow observation pool (not buy advice)."""
    if quotes.empty:
        return pd.DataFrame()
    pool = quotes[
        (quotes["一手资金"] <= cash)
        & (quotes["涨跌幅%"].between(-2, max_pct))
        & (quotes["状态"].isin(["站上均价", "均线上方", "修复中"]))
    ].copy()
    if pool.empty:
        return pool
    if "技术评分" in pool.columns:
        pool = pool[pool["技术评分"] >= 55]
        return pool.sort_values(["技术评分", "涨跌幅%"], ascending=[False, False])
    return pool.sort_values(["涨跌幅%", "成交额"], ascending=[False, False])


def build_position_plan(quotes: pd.DataFrame, total_capital: int, max_single_pct: float, reserve_pct: float) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()
    reserve_cash = total_capital * reserve_pct / 100
    tradable_capital = max(total_capital - reserve_cash, 0)
    single_budget = tradable_capital * max_single_pct / 100
    rows = []
    for _, row in quotes.iterrows():
        lot_cash = float(row["一手资金"])
        max_lots = int(single_budget // lot_cash) if lot_cash > 0 else 0
        rows.append(
            {
                "代码": row["代码"],
                "名称": row["名称"],
                "最新价": row["最新价"],
                "一手资金": lot_cash,
                "单票预算": single_budget,
                "最多可买手数": max_lots,
                "最多可买股数": max_lots * 100,
                "预算占用": max_lots * lot_cash,
            }
        )
    return pd.DataFrame(rows)


def build_t_dashboard(owned: pd.DataFrame) -> pd.DataFrame:
    if owned.empty:
        return pd.DataFrame()
    rows = []
    for _, row in owned.iterrows():
        price = float(row["最新价"])
        cost = float(row["成本"])
        high = float(row["日高"])
        low = float(row["日低"])
        avg = float(row["均价"]) if pd.notna(row.get("均价")) and row.get("均价") else price
        rng = max(high - low, 0.01)
        t_buy = min(avg, low + 0.35 * rng, cost * 0.99)
        t_sell = max(avg, low + 0.72 * rng, cost * 1.01)
        rows.append(
            {
                "代码": row["代码"],
                "名称": row["名称"],
                "最新价": price,
                "成本": cost,
                "T低吸观察价": round(t_buy, 3),
                "T高抛观察价": round(t_sell, 3),
                "日内波动%": round(rng / max(price, 0.01) * 100, 2),
            }
        )
    return pd.DataFrame(rows)


def build_main_force_score(quotes: pd.DataFrame) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()
    df = quotes.copy()
    rows = []
    for _, row in df.iterrows():
        price = float(row["最新价"])
        pct = float(row["涨跌幅%"])
        avg = row.get("均价")
        avg_ok = pd.notna(avg) and float(avg) > 0 and price >= float(avg)
        macd_ok = str(row.get("MACD信号", "")).find("金叉") >= 0 or str(row.get("MACD信号", "")).find("多头") >= 0
        kdj_ok = str(row.get("KDJ信号", "")).find("金叉") >= 0
        vol_ratio = float(row.get("量能比", 0) or 0)
        score = 0
        score += 25 if avg_ok else 0
        score += 20 if vol_ratio >= 1.2 else 0
        score += 20 if macd_ok else 0
        score += 15 if kdj_ok else 0
        score += 20 if pct >= 0 else 0
        rows.append(
            {
                "代码": row["代码"],
                "名称": row["名称"],
                "主力动向分": int(min(100, score)),
                "涨跌幅%": pct,
                "量能比": vol_ratio if vol_ratio else None,
                "状态": row.get("状态", "观察"),
                "结论": "主力活跃" if score >= 70 else "跟踪观察" if score >= 45 else "暂不跟随",
            }
        )
    out = pd.DataFrame(rows).sort_values(["主力动向分", "涨跌幅%"], ascending=[False, False])
    return out


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


def render_reference_rows(df: pd.DataFrame, value_col: str, value_class: str, empty_text: str) -> str:
    if df.empty:
        return f'<div class="muted">{html.escape(empty_text)}</div>'
    parts = []
    for idx, (_, row) in enumerate(df.head(5).iterrows(), 1):
        name = str(row.get("名称") or row.get("板块") or "-")
        code = str(row.get("代码") or "")
        pct = row.get("涨跌幅%")
        pct_text = f"{float(pct):+.2f}%" if pd.notna(pct) else "-"
        value = row.get(value_col, "")
        parts.append(
            f'<div class="flow-row">'
            f'<div class="rank-no">{idx}</div>'
            f'<div class="rank-main"><b>{html.escape(name)}</b><small>{html.escape(code)} {pct_text}</small></div>'
            f'<div class="{value_class}">{html.escape(str(value))}</div>'
            f"</div>"
        )
    return "".join(parts)


def render_reference_cockpit(bundle: dict[str, object]) -> None:
    if not bundle or not bundle.get("ok"):
        st.info("外部参考雷达暂未连接成功，本地行情与持仓模块不受影响。")
        return
    status = reference_status(bundle)
    report = reference_report(bundle)
    inflow = reference_flow_df(bundle, "inflow")
    outflow = reference_flow_df(bundle, "outflow")
    sectors = reference_sectors_df(bundle, 8)
    stocks = reference_stocks_df(bundle, 8)

    label = status.get("label") or report.get("market_tone") or "--"
    detail = status.get("detail") or status.get("monitor_detail") or "等待交易状态"
    generated = report.get("generated_at") or status.get("updated_at") or ""
    prompt = status.get("technical_prompt") or report.get("technical_prompt") or report.get("summary") or "等待外部市场提示。"
    top_sector = sectors.iloc[0]["板块"] if not sectors.empty else "-"
    top_stock = stocks.iloc[0]["名称"] if not stocks.empty else "-"
    source = bundle.get("base_url") or DEFAULT_REFERENCE_URL

    st.markdown(
        f"""
        <div class="cockpit">
          <div class="cockpit-head">
            <div>
              <div class="cockpit-title">外部市场雷达</div>
              <div class="cockpit-sub">参考源：{html.escape(str(source))} · 更新时间：{html.escape(str(generated or "-"))}</div>
            </div>
            <span class="pill">只作公开数据参考</span>
          </div>
          <div class="cockpit-grid">
            <div class="cockpit-card">
              <h4>市场状态</h4>
              <div class="market-state-main">
                <span class="badge badge-blue">{html.escape(str(label))}</span>
                <strong>{html.escape(str(detail))}</strong>
              </div>
              <div class="market-prompt">{html.escape(compact_text(prompt, 260))}</div>
              <div class="strip" style="margin-top:10px">
                <span class="pill">前排板块：{html.escape(str(top_sector))}</span>
                <span class="pill">前排热股：{html.escape(str(top_stock))}</span>
              </div>
            </div>
            <div class="cockpit-card">
              <h4>主力净流入</h4>
              {render_reference_rows(inflow, "主力净额文本", "money-in", "暂无主力流入数据")}
            </div>
            <div class="cockpit-card">
              <h4>主力净流出</h4>
              {render_reference_rows(outflow, "主力净额文本", "money-out", "暂无主力流出数据")}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_reference_tab(bundle: dict[str, object]) -> None:
    if not bundle or not bundle.get("ok"):
        st.warning("外部参考雷达暂不可用。可以稍后刷新，或关闭侧边栏的外部参考源。")
        return
    status = reference_status(bundle)
    report = reference_report(bundle)
    st.caption("外部公开数据源可能滞后或口径不同，仅用于研究和复盘。")
    cols = st.columns(4)
    cols[0].metric("外部状态", str(status.get("label") or report.get("market_tone") or "-"))
    cols[1].metric("板块数量", str(report.get("sector_count") or len(reference_sectors_df(bundle, 100))))
    cols[2].metric("热股数量", str(len(report.get("stocks") or [])))
    cols[3].metric("交易阶段", str(status.get("state") or "-"))

    prompt = status.get("technical_prompt") or report.get("technical_prompt") or ""
    if prompt:
        st.markdown("#### 外部技术提示")
        st.info(compact_text(prompt, 720))
    if not report:
        st.info("当前是轻量模式：已加载市场状态和主力资金。若要查看外部热点板块/全市场热股，请在左侧勾选“加载完整热点报告（较慢）”后刷新。")

    flow_in = reference_flow_df(bundle, "inflow")
    flow_out = reference_flow_df(bundle, "outflow")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("主力净流入")
        if flow_in.empty:
            st.info("暂无数据。")
        else:
            show = flow_in[["排名", "代码", "名称", "最新价", "涨跌幅%", "主力净额文本", "净占比", "换手率"]].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)
    with c2:
        st.subheader("主力净流出")
        if flow_out.empty:
            st.info("暂无数据。")
        else:
            show = flow_out[["排名", "代码", "名称", "最新价", "涨跌幅%", "主力净额文本", "净占比", "换手率"]].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)

    st.subheader("外部热点板块")
    sectors = reference_sectors_df(bundle, 30)
    if sectors.empty:
        st.info("暂无板块排行。")
    else:
        st.dataframe(sectors, use_container_width=True, hide_index=True)

    st.subheader("外部全市场热股")
    stocks = reference_stocks_df(bundle, 40)
    if stocks.empty:
        st.info("暂无热股排行。")
    else:
        st.dataframe(stocks, use_container_width=True, hide_index=True)


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


def render_indicator_guide() -> None:
    st.markdown(
        """
        <div class="panel">
          <h3>指标解释</h3>
          <div class="muted" style="line-height:1.8">
            <b>MACD</b>：看趋势拐点和强弱延续。金叉偏强、死叉偏弱，但高位金叉也可能是假信号。<br>
            <b>KDJ</b>：看短线节奏。金叉常见于反弹初段，J值过高容易出现震荡回落。<br>
            <b>RSI14</b>：看超买超卖。一般 70 上方偏热，30 下方偏冷，需结合趋势看。<br>
            <b>BOLL</b>：看价格在布林带中的位置。上轨附近偏强但易波动，下轨附近常见修复观察。<br>
            <b>MA5/10/20/60</b>：看均线结构。多头排列更强；跌破关键均线后先看承接与回收。<br>
            <b>量能比</b>：看资金活跃度。温和放量更健康，异常巨量要防冲高回落。<br>
            <b>技术评分</b>：综合观察分，不是买卖指令。请始终结合板块、资金和失效线。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def pick_mode(options: list[str], default: str) -> str:
    # Streamlit < 1.40 has no segmented_control.
    if hasattr(st, "segmented_control"):
        return st.segmented_control("模式", options, default=default, label_visibility="collapsed")
    idx = options.index(default) if default in options else 0
    return st.radio("模式", options, index=idx, horizontal=True, label_visibility="collapsed")


def main() -> None:
    st.set_page_config(page_title="A股短线王", page_icon="📊", layout="wide")
    inject_design()

    with st.sidebar:
        st.markdown("## 工作台")
        render_sidebar_card("交易设置", "盘中看承接与均价，复盘看主线持续性，低吸观察只筛修复不追高。")
        mode = pick_mode(["盘中", "复盘", "低吸观察"], "盘中")
        c_cash, c_pct = st.columns([1.05, 0.95])
        with c_cash:
            cash = st.number_input("一手资金上限", min_value=500, value=7000, step=500)
        with c_pct:
            max_watch_pct = st.number_input("观察涨幅上限", min_value=3.0, max_value=12.0, value=7.0, step=0.5, format="%.1f")
        max_watch_pct = st.slider("观察涨幅上限辅助滑杆", 3.0, 12.0, max_watch_pct, 0.5, label_visibility="collapsed")
        total_capital = st.number_input("总资金", min_value=1000, value=10000, step=500)
        p_col1, p_col2 = st.columns(2)
        with p_col1:
            max_single_pct = st.number_input("单票上限%", min_value=5.0, max_value=100.0, value=30.0, step=5.0, format="%.1f")
        with p_col2:
            reserve_pct = st.number_input("预留现金%", min_value=0.0, max_value=60.0, value=20.0, step=5.0, format="%.1f")

        st.markdown(
            f"""
            <div class="side-kpis">
              <div class="side-kpi"><div>一手资金</div><div>{int(cash)} 元</div></div>
              <div class="side-kpi"><div>追高过滤</div><div>{max_watch_pct:.1f}%</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"可交易资金约 {int(total_capital * (100 - reserve_pct) / 100)} 元；单票预算约 {int(total_capital * (100 - reserve_pct) / 100 * max_single_pct / 100)} 元")
        render_sidebar_card("股票池", "默认留空。你可自己填 6 位代码，空格或换行都可以；每次刷新会自动给出低吸观察和顺势观察候选。")
        codes_text = st.text_area("自选池", DEFAULT_CODES, height=128, label_visibility="collapsed", placeholder="示例：\n600487 000758 000733")
        code_count = len(set(parse_codes(codes_text)))
        st.caption(f"已识别 {code_count} 只自选股")
        full_scan = st.toggle("扩展板块全量扫描（更慢）", value=False, help="关闭时优先保证刷新速度；开启后会拉取更多板块样本。")

        render_sidebar_card("持仓账本", "每行：代码 股数 成本。示例：600111 200 51.75。这里只用于风险线和浮盈亏观察，不会连接券商下单。")
        positions_text = st.text_area(
            "持仓",
            DEFAULT_POSITIONS,
            height=110,
            label_visibility="collapsed",
            placeholder="示例（可多行）:\n600000 100 10.00\n000001 100 12.00",
        )
        st.caption("支持空格/逗号/冒号分隔，例如：600111,200,51.75 或 600111:200:51.75")
        pos_count = len(parse_positions(positions_text))
        st.caption(f"已识别 {pos_count} 条持仓")

        render_sidebar_card("指标引擎", "已启用 MACD、KDJ、RSI、BOLL、MA5/10/20/60、量能比和技术评分。评分只做观察，不替代纪律线。")
        render_sidebar_card("外部参考雷达", "可选接入公开市场工作台风格数据：市场状态、主力资金、热点板块和热股排行。慢或不可用时会自动降级。")
        enable_reference = st.checkbox("启用外部参考源", value=True)
        load_reference_report = st.checkbox("加载完整热点报告（较慢）", value=False)
        reference_url = st.text_input("参考源地址", DEFAULT_REFERENCE_URL, label_visibility="collapsed")

        if st.button("刷新行情", use_container_width=True):
            st.cache_data.clear()

    codes = set(parse_codes(codes_text))
    positions = parse_positions(positions_text)
    if not positions.empty:
        codes.update(positions["代码"].tolist())
    if full_scan:
        for group in SECTORS.values():
            codes.update(group)
    else:
        # Fast mode: keep one representative per sector for rotation context.
        for group in SECTORS.values():
            if group:
                codes.add(group[0])

    reference_bundle = dict(fetch_reference_bundle(reference_url, bool(enable_reference)))
    if enable_reference and load_reference_report:
        reference_bundle["report"] = fetch_reference_report_payload(reference_url, True)
    indices = fetch_indices()
    ref_indices = reference_indices_df(reference_bundle)
    if indices.empty and not ref_indices.empty:
        indices = ref_indices
    quotes = get_quotes(tuple(codes))
    now_dt = cn_now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    phase = market_phase(now_dt)
    trade_state = trading_day_status(now_dt)
    temp, temp_note = index_temperature(indices)

    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-title">A股短线王</div>
          <div class="hero-sub">更新时间（北京时间）：{now}　交易状态：{trade_state}　市场阶段：{phase}　模式：{mode}　以下内容不构成个性化投资建议</div>
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
    if enable_reference:
        render_reference_cockpit(reference_bundle)

    left, right = st.columns([1.12, 0.88])
    with left:
        render_signals(signals)
    with right:
        render_observation_windows(quotes, positions, rotation)

    render_tech_matrix(quotes)

    tab_digest, tab_external, tab_tech, tab_hold, tab_rotation, tab_watch, tab_quant, tab_backtest, tab_journal, tab_text = st.tabs(
        ["盘面总览", "外部雷达", "技术指标", "持仓雷达", "风扇蜂巢", "观察池", "量化工具", "回测工具", "交易复盘", "文本合集"]
    )

    with tab_digest:
        st.subheader("主线排序")
        if rotation.empty:
            st.info("暂无板块轮动数据。")
        else:
            summary = rotation.head(6).copy()
            summary["成交额"] = summary["成交额"].map(cn_money)
            st.dataframe(summary, use_container_width=True, hide_index=True)
        st.subheader("自选强弱分布")
        rank = quotes[["代码", "名称", "最新价", "涨跌幅%", "状态", "一手资金", "成交额", "换手%", "日高", "日低"]].copy()
        rank["成交额"] = rank["成交额"].map(cn_money)
        st.dataframe(rank.sort_values("涨跌幅%", ascending=False), use_container_width=True, hide_index=True)

    with tab_external:
        render_reference_tab(reference_bundle)

    with tab_tech:
        render_indicator_guide()
        st.subheader("技术评分排行")
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
        tech_sorted = quotes[available_cols].sort_values("技术评分", ascending=False)
        st.dataframe(tech_sorted, use_container_width=True, hide_index=True)
        st.subheader("量价共振观察")
        cols_focus = [c for c in ["代码", "名称", "最新价", "涨跌幅%", "量能比", "MACD信号", "KDJ信号", "均线结构", "状态"] if c in quotes.columns]
        focus = quotes[cols_focus].copy()
        if "量能比" in focus.columns:
            focus = focus.sort_values(["量能比", "涨跌幅%"], ascending=[False, False])
        st.dataframe(focus.head(20), use_container_width=True, hide_index=True)
        st.caption("技术评分用于观察强弱共振，不代表确定性买卖点。MACD/KDJ 金叉需要结合位置、量能和板块主线确认。")

    with tab_hold:
        if owned.empty:
            st.info("左侧输入持仓后，这里会显示成本线、浮盈亏和风险状态。")
        else:
            hold = owned.copy()
            hold["成本距离%"] = (hold["最新价"] / hold["成本"] - 1) * 100
            hold["日内位置%"] = ((hold["最新价"] - hold["日低"]) / (hold["日高"] - hold["日低"]).replace(0, 0.01) * 100).clip(0, 100)
            hold["止损线(-3%)"] = hold["成本"] * 0.97
            hold["止损线(-5%)"] = hold["成本"] * 0.95
            hold["止盈线1(+6%)"] = hold["成本"] * 1.06
            hold["止盈线2(+10%)"] = hold["成本"] * 1.10
            st.dataframe(
                hold[["代码", "名称", "股数", "成本", "最新价", "成本距离%", "浮盈亏", "浮盈亏%", "止损线(-3%)", "止损线(-5%)", "止盈线1(+6%)", "止盈线2(+10%)", "状态", "均价", "日高", "日低"]],
                use_container_width=True,
                hide_index=True,
            )
            for _, row in hold.iterrows():
                st.progress(float(row["日内位置%"]) / 100, text=f"{row['名称']} 日内位置 {row['日内位置%']:.0f}% | 成本距离 {row['成本距离%']:+.2f}%")

    with tab_rotation:
        show = rotation.copy()
        if not show.empty:
            show["成交额"] = show["成交额"].map(cn_money)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.bar_chart(rotation.set_index("板块叶片")["风扇分"])
            st.subheader("风叶雷达")
            radar = build_fan_radar(rotation)[["板块叶片", "风叶阶段", "状态", "风扇分", "甜点分", "代表股"]].copy()
            st.dataframe(radar, use_container_width=True, hide_index=True)
            st.subheader("板块热力")
            heat = build_fan_radar(rotation)[["板块叶片", "风叶阶段", "风扇分", "甜点分"]].sort_values("风扇分", ascending=False)
            st.dataframe(heat, use_container_width=True, hide_index=True)
            st.subheader("轮动时钟")
            clock = build_rotation_clock(rotation)
            st.dataframe(clock, use_container_width=True, hide_index=True)
            honey = rotation[["板块叶片", "状态", "风扇分", "代表股"]].copy()
            honey["蜂蜜甜度"] = honey["风扇分"].rank(pct=True) * 100
            honey["资金判断"] = honey["状态"].map({"加速/高潮": "甜但拥挤", "启动": "资金主动流入", "修复/潜伏": "等待确认", "分歧": "换手分歧", "退潮": "资金撤退"}).fillna("观察")
            st.subheader("蜂巢资金迁徙")
            st.dataframe(honey.sort_values("蜂蜜甜度", ascending=False), use_container_width=True, hide_index=True)

    with tab_watch:
        st.caption("以下是观察池，不构成个性化投资建议。")
        bottom_watch = make_bottom_watchlist(quotes, int(cash))
        entry_watch = make_entry_watchlist(quotes, int(cash), max_watch_pct)
        if bottom_watch.empty and entry_watch.empty:
            st.warning("当前没有符合资金和过滤条件的观察票。")
        else:
            st.subheader("低吸观察（抄底观察）")
            if bottom_watch.empty:
                st.info("当前暂无合格低吸观察标的。")
            else:
                bottom_show = bottom_watch[["代码", "名称", "最新价", "涨跌幅%", "状态", "一手资金", "技术评分", "成交额", "日高", "日低"]].copy()
                bottom_show["成交额"] = bottom_show["成交额"].map(cn_money)
                st.dataframe(bottom_show.head(12), use_container_width=True, hide_index=True)

            st.subheader("顺势观察（适合入场观察）")
            if entry_watch.empty:
                st.info("当前暂无合格顺势观察标的。")
            else:
                entry_show = entry_watch[["代码", "名称", "最新价", "涨跌幅%", "状态", "一手资金", "技术评分", "成交额", "日高", "日低"]].copy()
                entry_show["成交额"] = entry_show["成交额"].map(cn_money)
                st.dataframe(entry_show.head(12), use_container_width=True, hide_index=True)

            st.subheader("仓位管理器（按你的资金自动测算）")
            sizing_base = pd.concat([bottom_watch.head(8), entry_watch.head(8)], ignore_index=True).drop_duplicates("代码")
            if sizing_base.empty:
                st.info("暂无可测算标的。")
            else:
                plan = build_position_plan(sizing_base, int(total_capital), float(max_single_pct), float(reserve_pct))
                plan["预算占用"] = plan["预算占用"].map(lambda x: f"{x:.0f}")
                plan["单票预算"] = plan["单票预算"].map(lambda x: f"{x:.0f}")
                st.dataframe(plan[["代码", "名称", "最新价", "一手资金", "单票预算", "最多可买手数", "最多可买股数", "预算占用"]], use_container_width=True, hide_index=True)

            st.subheader("下一步确认")
            merged_watch = pd.concat([bottom_watch.head(3), entry_watch.head(3)], ignore_index=True).drop_duplicates("代码")
            for _, row in merged_watch.iterrows():
                st.markdown(f"- **{row['名称']} {row['代码']}**：看 `{row['日高']:.2f}` 是否突破，看 `{row['日低']:.2f}` 是否失守。")

    with tab_quant:
        st.caption("以下为量化观察工具，不构成个性化投资建议。")
        t_panel = build_t_dashboard(owned)
        st.subheader("做T辅助")
        if t_panel.empty:
            st.info("先在左侧输入持仓，系统会自动给出T低吸/高抛观察价。")
        else:
            st.dataframe(t_panel, use_container_width=True, hide_index=True)
            st.caption("做T观察逻辑：靠近低吸观察价看承接，接近高抛观察价看冲高回落风险。")

        st.subheader("主力动向")
        mf = build_main_force_score(quotes)
        if mf.empty:
            st.info("暂无可计算标的。")
        else:
            st.dataframe(mf.head(20), use_container_width=True, hide_index=True)
            st.caption("主力动向分由：站上均价、量能比、MACD/KDJ、当日强弱共同计算。")

    with tab_backtest:
        st.caption("回测用于验证策略历史表现，不构成个性化投资建议。回测按次日开盘执行信号、A股整手买入，并计入手续费、印花税和滑点。")
        quote_names = dict(zip(quotes["代码"], quotes["名称"]))
        default_backtest_codes = sorted(set(quotes["代码"].astype(str).tolist()))
        if not default_backtest_codes:
            default_backtest_codes = sorted(codes)
        with st.form("backtest_form"):
            source = st.radio("回测范围", ["当前股票池", "当前持仓", "手动输入"], horizontal=True)
            if source == "当前持仓" and not positions.empty:
                default_text = " ".join(positions["代码"].astype(str).tolist())
            elif source == "手动输入":
                default_text = ""
            else:
                default_text = " ".join(default_backtest_codes)
            backtest_text = st.text_area(
                "股票代码",
                value=default_text,
                height=90,
                placeholder="示例：600000 000001 601318",
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                strategy = st.selectbox("策略", ["MA5上穿MA20", "MACD金叉死叉", "KDJ低位金叉", "20日新高突破", "均线+MACD共振"])
            with c2:
                limit = st.slider("回测交易日", min_value=80, max_value=720, value=260, step=20)
            with c3:
                initial_cash = st.number_input("单票初始资金", min_value=2000, value=10000, step=1000)
            c4, c5, c6, c7 = st.columns(4)
            with c4:
                fee_bps = st.number_input("佣金 万分之", min_value=0.0, value=3.0, step=0.5, format="%.1f")
            with c5:
                stamp_tax_pct = st.number_input("卖出印花税%", min_value=0.0, value=0.05, step=0.01, format="%.2f")
            with c6:
                slippage_pct = st.number_input("滑点%", min_value=0.0, value=0.10, step=0.05, format="%.2f")
            with c7:
                stop_loss_pct = st.number_input("止损%", min_value=1.0, value=6.0, step=0.5, format="%.1f")
            take_profit_pct = st.slider("止盈触发%", min_value=3.0, max_value=30.0, value=12.0, step=1.0)
            submitted = st.form_submit_button("开始批量回测", use_container_width=True)

        if submitted:
            backtest_codes = sorted(set(parse_codes(backtest_text)))
            if not backtest_codes:
                st.warning("请输入至少一只 6 位股票代码。")
            else:
                progress = st.progress(0.0, text="正在拉取K线并回测...")
                summaries = []
                details: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
                for idx, code in enumerate(backtest_codes, 1):
                    summary, curve, trades = run_single_backtest(
                        code,
                        quote_names.get(code, code),
                        strategy,
                        int(limit),
                        float(initial_cash),
                        float(fee_bps),
                        float(stamp_tax_pct),
                        float(slippage_pct),
                        float(stop_loss_pct),
                        float(take_profit_pct),
                    )
                    summaries.append(summary)
                    details[code] = (curve, trades)
                    progress.progress(idx / len(backtest_codes), text=f"已回测 {idx}/{len(backtest_codes)}：{code}")
                result = pd.DataFrame(summaries)
                if not result.empty:
                    result = result.sort_values(["总收益%", "最大回撤%"], ascending=[False, False], na_position="last")
                st.session_state["backtest_result"] = result
                st.session_state["backtest_detail"] = details
                st.session_state["backtest_strategy"] = strategy
                progress.empty()

        result = st.session_state.get("backtest_result")
        details = st.session_state.get("backtest_detail", {})
        if isinstance(result, pd.DataFrame) and not result.empty:
            st.subheader("回测排名")
            show = result.copy()
            for col in ["总收益%", "买入持有%", "超额%", "最大回撤%", "胜率%"]:
                if col in show.columns:
                    show[col] = show[col].map(lambda x: "-" if pd.isna(x) else f"{float(x):+.2f}%")
            st.dataframe(show, use_container_width=True, hide_index=True)
            valid_codes = [code for code in result["代码"].astype(str).tolist() if code in details]
            selected = st.selectbox("查看单票细节", valid_codes, format_func=lambda code: f"{quote_names.get(code, code)} {code}")
            curve, trades = details.get(selected, (pd.DataFrame(), pd.DataFrame()))
            if isinstance(curve, pd.DataFrame) and not curve.empty:
                chart = curve.copy()
                chart["日期"] = pd.to_datetime(chart["日期"])
                st.line_chart(chart.set_index("日期")[["资产曲线", "买入持有"]])
            if isinstance(trades, pd.DataFrame) and not trades.empty:
                trade_show = trades.copy()
                trade_show["买入价"] = trade_show["买入价"].map(lambda x: f"{float(x):.2f}")
                trade_show["卖出价"] = trade_show["卖出价"].map(lambda x: f"{float(x):.2f}")
                trade_show["收益%"] = trade_show["收益%"].map(lambda x: f"{float(x):+.2f}%")
                st.subheader("交易明细")
                st.dataframe(trade_show, use_container_width=True, hide_index=True)
            else:
                st.info("该策略在这只股票上没有形成完整卖出交易，可能仍处于持仓或信号不足。")

    with tab_journal:
        st.caption("记录你的交易动作和结果，用于复盘统计。")
        with st.form("trade_journal_form", clear_on_submit=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                trade_date = st.date_input("日期", value=dt.date.today())
            with c2:
                trade_code = st.text_input("代码", placeholder="如 600487")
            with c3:
                trade_name = st.text_input("名称", placeholder="如 亨通光电")
            c4, c5, c6, c7 = st.columns(4)
            with c4:
                direction = st.selectbox("方向", ["买入", "卖出"])
            with c5:
                trade_price = st.number_input("价格", min_value=0.0, value=0.0, step=0.01, format="%.2f")
            with c6:
                trade_shares = st.number_input("股数", min_value=0, value=100, step=100)
            with c7:
                result_pct = st.number_input("结果%（平仓后填）", value=0.0, step=0.1, format="%.2f")
            reason = st.text_input("理由", placeholder="如 回踩MA10缩量企稳")
            note = st.text_input("备注", placeholder="如 失效线跌破执行")
            submitted = st.form_submit_button("写入日志")
            if submitted and re.fullmatch(r"\d{6}", (trade_code or "").strip()):
                append_trade_log(
                    {
                        "日期": str(trade_date),
                        "代码": trade_code.strip(),
                        "名称": trade_name.strip(),
                        "方向": direction,
                        "价格": float(trade_price),
                        "股数": int(trade_shares),
                        "理由": reason.strip(),
                        "结果%": float(result_pct),
                        "备注": note.strip(),
                    }
                )
                st.success("已写入交易日志。")
            elif submitted:
                st.error("代码格式需为 6 位数字。")

        journal = load_trade_log()
        if journal.empty:
            st.info("暂无交易日志。")
        else:
            st.dataframe(journal.sort_values("日期", ascending=False), use_container_width=True, hide_index=True)
            valid = pd.to_numeric(journal["结果%"], errors="coerce").dropna()
            if not valid.empty:
                win_rate = (valid > 0).mean() * 100
                avg_win = valid[valid > 0].mean() if (valid > 0).any() else 0.0
                avg_loss = valid[valid <= 0].mean() if (valid <= 0).any() else 0.0
                pnl_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
                m1, m2, m3 = st.columns(3)
                m1.metric("已记录样本", f"{len(valid)}")
                m2.metric("胜率", f"{win_rate:.1f}%")
                m3.metric("盈亏比", f"{pnl_ratio:.2f}")
            else:
                st.caption("结果% 为空时，仅记录行为，不参与胜率统计。")

    with tab_text:
        st.text_area("可复制文本", digest_text(indices, quotes, positions, rotation), height=520)


if __name__ == "__main__":
    main()
