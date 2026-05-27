#!/usr/bin/env python3
"""Streamlit visual app for the Daily A-Share Dynamic Digest skill.

Run:
    streamlit run apps/a_share_visual_app.py

This app is a research dashboard only. It does not provide investment advice.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from a_share_watch import fetch_tencent, fetch_eastmoney_one
except Exception:  # pragma: no cover - Streamlit will display a useful error.
    fetch_tencent = None
    fetch_eastmoney_one = None


CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"


DEFAULT_SECTORS = {
    "光通信/海缆/CPO": ["600487", "600522", "002491"],
    "稀土/有色/磁材": ["000758", "600111", "600366"],
    "军工电子/电子元件": ["000733", "603678", "000636"],
    "电力/能源/装备": ["600396", "000400", "600312"],
    "低价题材/机器人": ["002031", "002421", "002527"],
    "商业航天": ["603601", "600118", "002025"],
}


@dataclasses.dataclass
class ScanRow:
    code: str
    name: str
    price: float
    pct: float
    high: float
    low: float
    prev_close: float
    amount: float
    turnover: float
    net_main: float

    @property
    def lot_cash(self) -> float:
        return self.price * 100

    @property
    def close_pos(self) -> float:
        width = self.high - self.low
        return 0.5 if width <= 0 else (self.price - self.low) / width


def fetch_url(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AShareVisualApp/1.0",
            "Referer": "https://finance.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


@st.cache_data(ttl=45)
def get_quotes(codes: tuple[str, ...]) -> pd.DataFrame:
    codes = tuple(sorted({code for code in codes if re.fullmatch(r"\d{6}", code)}))
    if not codes:
        return pd.DataFrame()
    quotes = {}
    if fetch_tencent:
        try:
            quotes = fetch_tencent(codes)
        except Exception:
            quotes = {}
    if fetch_eastmoney_one:
        for code in codes:
            if code not in quotes:
                q = fetch_eastmoney_one(code)
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


def fetch_scan_page(page: int, page_size: int, sort_field: str) -> list[dict]:
    params = {
        "pn": page,
        "pz": page_size,
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": sort_field,
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f4,f6,f8,f12,f14,f15,f16,f18,f62",
    }
    raw = fetch_url(f"{CLIST_URL}?{urllib.parse.urlencode(params)}")
    return (json.loads(raw.decode("utf-8")).get("data") or {}).get("diff") or []


def ordinary_main_board(code: str) -> bool:
    if code.startswith(("300", "301", "688", "689", "8", "4", "920")):
        return False
    return code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def parse_scan_row(item: dict) -> ScanRow | None:
    try:
        code = str(item["f12"])
        name = str(item["f14"])
        if not ordinary_main_board(code) or "ST" in name.upper() or "退" in name:
            return None
        return ScanRow(
            code=code,
            name=name,
            price=float(item["f2"]),
            pct=float(item["f3"]),
            high=float(item["f15"]),
            low=float(item["f16"]),
            prev_close=float(item["f18"]),
            amount=float(item["f6"]),
            turnover=float(item["f8"]),
            net_main=float(item.get("f62") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def repair_score(row: ScanRow) -> float:
    score = 0.0
    if -4.5 <= row.pct <= 2.5:
        score += 25
    elif -7 <= row.pct < -4.5:
        score += 10
    elif 2.5 < row.pct <= 5:
        score += 8
    else:
        score -= 20
    if row.close_pos >= 0.65:
        score += 25
    elif row.close_pos >= 0.45:
        score += 14
    elif row.close_pos >= 0.3:
        score += 5
    else:
        score -= 15
    if row.amount >= 1_000_000_000:
        score += 15
    elif row.amount >= 300_000_000:
        score += 8
    else:
        score -= 5
    if 2 <= row.turnover <= 12:
        score += 15
    elif 12 < row.turnover <= 20:
        score += 5
    elif row.turnover > 30:
        score -= 15
    if row.net_main > 50_000_000:
        score += 15
    elif row.net_main > 0:
        score += 8
    elif row.net_main < -100_000_000:
        score -= 12
    if row.lot_cash <= 2500:
        score += 5
    elif row.lot_cash > 7000:
        score -= 6
    return score


@st.cache_data(ttl=120)
def scan_market(pages: int, page_size: int) -> pd.DataFrame:
    seen: dict[str, ScanRow] = {}
    for sort_field in ("f3", "f62"):
        for page in range(1, pages + 1):
            try:
                items = fetch_scan_page(page, page_size, sort_field)
            except Exception:
                continue
            for item in items:
                row = parse_scan_row(item)
                if row:
                    seen[row.code] = row
    rows = []
    for row in seen.values():
        score = repair_score(row)
        rows.append(
            {
                "代码": row.code,
                "名称": row.name,
                "最新价": row.price,
                "涨跌幅%": row.pct,
                "日内位置%": row.close_pos * 100,
                "一手资金": row.lot_cash,
                "成交额": row.amount,
                "换手%": row.turnover,
                "主力净额": row.net_main,
                "修复分": score,
                "阶段": stage_label(row, score),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("修复分", ascending=False)


def stage_label(row: ScanRow, score: float) -> str:
    if row.pct >= 7:
        return "加速/高潮"
    if score >= 65:
        return "修复确认"
    if score >= 45:
        return "潜伏/启动"
    if row.pct < -5 and row.close_pos < 0.35:
        return "退潮"
    return "观察"


def sector_rotation(quotes: pd.DataFrame, sectors: dict[str, list[str]]) -> pd.DataFrame:
    rows = []
    for sector, codes in sectors.items():
        part = quotes[quotes["代码"].isin(codes)]
        if part.empty:
            continue
        avg_pct = part["涨跌幅%"].mean()
        above_mid = 0
        usable_mid = 0
        for _, row in part.iterrows():
            mid = row.get("均价")
            if pd.notna(mid) and mid:
                usable_mid += 1
                above_mid += int(row["最新价"] >= mid)
        amount = part["成交额"].fillna(0).sum()
        fan_score = avg_pct * 8 + (above_mid / usable_mid * 20 if usable_mid else 0) + math.log10(amount + 1)
        if avg_pct >= 5:
            stage = "加速/高潮"
        elif avg_pct >= 1 and fan_score >= 20:
            stage = "启动"
        elif -2 <= avg_pct < 1:
            stage = "修复/潜伏"
        elif avg_pct < -4:
            stage = "退潮"
        else:
            stage = "分歧"
        rows.append(
            {
                "叶片/板块": sector,
                "代表股": "、".join(part["名称"].astype(str).tolist()),
                "平均涨跌幅%": avg_pct,
                "站均价数": f"{above_mid}/{usable_mid}" if usable_mid else "-",
                "成交额合计": amount,
                "风扇分": fan_score,
                "状态": stage,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("风扇分", ascending=False)


def honeycomb_view(rotation: pd.DataFrame) -> pd.DataFrame:
    if rotation.empty:
        return pd.DataFrame()
    df = rotation.copy()
    df["蜂蜜甜度"] = df["风扇分"].rank(pct=True) * 100
    df["资金判断"] = df["状态"].map(
        {
            "启动": "蜜蜂试探流入",
            "修复/潜伏": "等待确认",
            "加速/高潮": "甜但拥挤",
            "分歧": "分歧换手",
            "退潮": "蜂群撤退",
        }
    ).fillna("观察")
    return df[["叶片/板块", "蜂蜜甜度", "资金判断", "代表股"]].sort_values("蜂蜜甜度", ascending=False)


def style_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}"


def main() -> None:
    st.set_page_config(page_title="每日A股动态合集", page_icon="📈", layout="wide")
    st.title("每日A股动态合集")
    st.caption("研究观察工具，不构成个性化投资建议。行情源可能延迟或不可用，交易前请以券商和交易所数据为准。")

    with st.sidebar:
        st.header("输入")
        codes_text = st.text_area(
            "自选股代码",
            value="600487 000758 000733 603678 000636 600522 603601 600396 002491",
            height=90,
        )
        positions_text = st.text_area(
            "持仓：代码 股数 成本",
            value="600487 200 68.82\n000758 300 6.893",
            height=90,
        )
        cash = st.number_input("可用资金/观察资金", min_value=0, value=10000, step=500)
        scan_pages = st.slider("全市场扫描页数", 1, 20, 8)
        run_scan = st.checkbox("运行普通主板修复扫描", value=False)
        refresh = st.button("刷新数据")

    codes = set(parse_codes(codes_text))
    pos_df = parse_positions(positions_text)
    codes.update(pos_df["代码"].tolist() if not pos_df.empty else [])
    for sector_codes in DEFAULT_SECTORS.values():
        codes.update(sector_codes)
    if refresh:
        st.cache_data.clear()

    quotes = get_quotes(tuple(codes))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"更新时间：{now}")

    if quotes.empty:
        st.warning("暂未获取到行情。请检查网络、行情源或代码格式。")
        return

    tab_hold, tab_fan, tab_scan, tab_about = st.tabs(["持仓与自选", "风扇/蜂巢", "修复扫描", "说明"])

    with tab_hold:
        merged = quotes.copy()
        if not pos_df.empty:
            merged = merged.merge(pos_df, on="代码", how="left")
            merged["浮盈亏"] = (merged["最新价"] - merged["成本"]) * merged["股数"]
            merged["浮盈亏%"] = (merged["最新价"] / merged["成本"] - 1) * 100
        st.dataframe(
            merged.sort_values("涨跌幅%", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "成交额": st.column_config.TextColumn("成交额"),
            },
        )
        owned = merged[merged.get("股数", pd.Series(index=merged.index)).notna()] if "股数" in merged else pd.DataFrame()
        if not owned.empty:
            total_pnl = owned["浮盈亏"].sum()
            st.metric("持仓浮盈亏（未扣手续费）", f"{total_pnl:+.2f} 元")
        watch = quotes[(quotes["一手资金"] <= cash) & (quotes["涨跌幅%"].between(-4.5, 5))]
        st.subheader("资金适配观察")
        st.dataframe(watch[["代码", "名称", "最新价", "涨跌幅%", "一手资金", "日高", "日低"]], use_container_width=True, hide_index=True)

    with tab_fan:
        rotation = sector_rotation(quotes, DEFAULT_SECTORS)
        st.subheader("风扇叶片")
        if rotation.empty:
            st.info("当前代表股行情不足，无法生成叶片状态。")
        else:
            show = rotation.copy()
            show["成交额合计"] = show["成交额合计"].map(style_money)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.bar_chart(rotation.set_index("叶片/板块")["风扇分"])
        st.subheader("蜂巢资金迁徙")
        honey = honeycomb_view(rotation)
        if honey.empty:
            st.info("暂无蜂巢评分。")
        else:
            st.dataframe(honey, use_container_width=True, hide_index=True)

    with tab_scan:
        st.write("普通沪深主板修复/低吸扫描会排除科创板、北交所、创业板、ST 和退市风险名称。")
        if run_scan:
            scanned = scan_market(scan_pages, 200)
            if scanned.empty:
                st.warning("扫描源暂不可用或返回为空。")
            else:
                scanned_show = scanned.copy()
                scanned_show["成交额"] = scanned_show["成交额"].map(style_money)
                scanned_show["主力净额"] = scanned_show["主力净额"].map(style_money)
                st.dataframe(scanned_show.head(80), use_container_width=True, hide_index=True)
        else:
            st.info("打开左侧开关后运行扫描。")

    with tab_about:
        st.markdown(
            """
            ### 使用逻辑

            - **风扇理论**：看板块叶片处在潜伏、启动、加速、分歧、退潮还是修复。
            - **蜂巢理论**：看资金像蜜蜂一样在不同板块之间迁徙，甜度高但拥挤的板块要防兑现。
            - **修复扫描**：找普通主板中“跌不深、收得上来、有成交、有承接”的观察票。

            所有表格都是观察工具，不是买卖指令。实盘前请核对券商行情、公告、交易权限和自身风险承受能力。
            """
        )


if __name__ == "__main__":
    main()
