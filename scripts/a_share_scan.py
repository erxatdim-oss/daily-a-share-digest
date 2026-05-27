#!/usr/bin/env python3
"""Scan A-share candidates from Eastmoney quote list.

This is a research aid. It excludes common special-permission markets by default
and ranks ordinary Shanghai/Shenzhen main-board names with simple transparent
factors.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import time
import urllib.parse
import urllib.request


CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"


@dataclasses.dataclass
class StockRow:
    code: str
    name: str
    price: float
    pct: float
    change: float
    high: float
    low: float
    open_price: float
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
        if width <= 0:
            return 0.5
        return (self.price - self.low) / width

    @property
    def amplitude(self) -> float:
        if self.prev_close <= 0:
            return 0.0
        return (self.high - self.low) / self.prev_close * 100


def fetch_page(page: int, page_size: int, sort_field: str) -> list[dict]:
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
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21,f62",
    }
    url = f"{CLIST_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AShareScan/1.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("data") or {}).get("diff") or []


def is_ordinary_main_board(code: str) -> bool:
    if code.startswith(("300", "301", "688", "689", "8", "4", "920")):
        return False
    return code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))


def parse_row(item: dict) -> StockRow | None:
    try:
        code = str(item["f12"])
        name = str(item["f14"])
        if "ST" in name.upper() or "退" in name:
            return None
        return StockRow(
            code=code,
            name=name,
            price=float(item["f2"]),
            pct=float(item["f3"]),
            change=float(item["f4"]),
            high=float(item["f15"]),
            low=float(item["f16"]),
            open_price=float(item["f17"]),
            prev_close=float(item["f18"]),
            amount=float(item["f6"]),
            turnover=float(item["f8"]),
            net_main=float(item.get("f62") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def repair_score(row: StockRow) -> float:
    """Score bottom/recovery setups, not pure momentum breakouts."""
    score = 0.0
    # Prefer stocks that are red or mildly green, not extended limit-up names.
    if -4.5 <= row.pct <= 2.5:
        score += 25
    elif -7 <= row.pct < -4.5:
        score += 10
    elif 2.5 < row.pct <= 5:
        score += 8
    else:
        score -= 20

    # Close away from the low is repair; close pinned to low is falling knife.
    if row.close_pos >= 0.65:
        score += 25
    elif row.close_pos >= 0.45:
        score += 14
    elif row.close_pos >= 0.3:
        score += 5
    else:
        score -= 15

    # Liquidity and turnover.
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

    # Main fund inflow helps, but do not overfit it.
    if row.net_main > 50_000_000:
        score += 15
    elif row.net_main > 0:
        score += 8
    elif row.net_main < -100_000_000:
        score -= 12

    # Affordability for small/medium accounts.
    if row.lot_cash <= 2500:
        score += 5
    elif row.lot_cash > 7000:
        score -= 6

    return score


def format_money(value: float) -> str:
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan ordinary-main-board A-share candidates")
    parser.add_argument("--pages", type=int, default=8, help="number of Eastmoney pages to scan")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    seen: dict[str, StockRow] = {}
    # f3 desc catches hot names; f62 desc catches money; f3 asc catches dips.
    for sort_field in ("f3", "f62"):
        for page in range(1, args.pages + 1):
            try:
                items = fetch_page(page, args.page_size, sort_field)
            except Exception:
                continue
            for item in items:
                row = parse_row(item)
                if row and is_ordinary_main_board(row.code):
                    seen[row.code] = row
            time.sleep(0.05)

    rows = list(seen.values())
    scored = sorted(((repair_score(row), row) for row in rows), key=lambda pair: pair[0], reverse=True)

    print("以下是A股普通主板修复/低吸观察扫描，不构成个性化投资建议。")
    print(f"扫描普通主板样本：{len(rows)} 只")
    print("")
    for score, row in scored[: args.top]:
        print(
            f"{row.name} {row.code} 分数 {score:.1f} | 最新 {row.price:.2f} "
            f"{row.pct:+.2f}% | 位置 {row.close_pos:.0%} | 一手 {row.lot_cash:.0f}元 | "
            f"成交额 {format_money(row.amount)} | 换手 {row.turnover:.2f}% | "
            f"主力净额 {format_money(row.net_main)} | 高低 {row.high:.2f}-{row.low:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
