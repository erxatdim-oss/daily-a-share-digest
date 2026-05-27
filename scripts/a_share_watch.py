#!/usr/bin/env python3
"""Lightweight A-share watch tool for intraday position checks.

The script uses public quote endpoints and prints a concise Chinese report.
It is a research aid only, not investment advice.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable


TENCENT_URL = "http://qt.gtimg.cn/q={symbols}"
EASTMONEY_URL = (
    "https://push2.eastmoney.com/api/qt/stock/get"
    "?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170,f171"
)


@dataclasses.dataclass
class Quote:
    code: str
    name: str
    price: float
    prev_close: float
    open_price: float
    high: float
    low: float
    volume_lot: float | None
    amount: float | None
    turnover: float | None
    avg_price: float | None
    pct: float
    change: float
    source: str
    timestamp: str | None = None

    @property
    def lot_cash(self) -> float:
        return self.price * 100


@dataclasses.dataclass
class Position:
    code: str
    shares: int
    cost: float


def market_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    return "sz"


def eastmoney_secid(code: str) -> str:
    market = "1" if code.startswith(("6", "9")) else "0"
    return f"{market}.{code}"


def fetch_url(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AShareWatch/1.0",
            "Referer": "https://finance.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_float(value: str | int | float | None, scale: float = 1.0) -> float:
    if value in (None, "", "-"):
        return 0.0
    return float(value) / scale


def fetch_tencent(codes: Iterable[str]) -> dict[str, Quote]:
    symbols = ",".join(f"{market_prefix(code)}{code}" for code in codes)
    raw = fetch_url(TENCENT_URL.format(symbols=urllib.parse.quote(symbols, safe=",")))
    text = raw.decode("gbk", errors="replace")
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
            open_price = parse_float(fields[5])
            high = parse_float(fields[33])
            low = parse_float(fields[34])
            change = parse_float(fields[31])
            pct = parse_float(fields[32])
            amount = parse_float(fields[37]) * 10000 if fields[37] else None
            turnover = parse_float(fields[38]) if len(fields) > 38 else None
            avg_price = parse_float(fields[51]) if len(fields) > 51 else None
            volume_lot = parse_float(fields[36]) if len(fields) > 36 else None
        except (ValueError, IndexError):
            continue
        quotes[code] = Quote(
            code=code,
            name=fields[1],
            price=price,
            prev_close=prev_close,
            open_price=open_price,
            high=high,
            low=low,
            volume_lot=volume_lot,
            amount=amount,
            turnover=turnover,
            avg_price=avg_price,
            pct=pct,
            change=change,
            source="Tencent",
            timestamp=fields[30] if len(fields) > 30 else None,
        )
    return quotes


def fetch_eastmoney_one(code: str) -> Quote | None:
    import json

    url = EASTMONEY_URL.format(secid=eastmoney_secid(code))
    try:
        raw = fetch_url(url)
        data = json.loads(raw.decode("utf-8")).get("data") or {}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return None
    if not data:
        return None
    price = parse_float(data.get("f43"), 100)
    prev_close = parse_float(data.get("f60"), 100)
    high = parse_float(data.get("f44"), 100)
    low = parse_float(data.get("f45"), 100)
    open_price = parse_float(data.get("f46"), 100)
    pct = parse_float(data.get("f170"), 100)
    change = price - prev_close if prev_close else 0.0
    return Quote(
        code=code,
        name=str(data.get("f58") or code),
        price=price,
        prev_close=prev_close,
        open_price=open_price,
        high=high,
        low=low,
        volume_lot=parse_float(data.get("f47")),
        amount=parse_float(data.get("f48")),
        turnover=parse_float(data.get("f168"), 100),
        avg_price=None,
        pct=pct,
        change=change,
        source="Eastmoney",
    )


def parse_position(value: str) -> Position:
    parts = value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("position format must be CODE:SHARES:COST")
    code, shares, cost = parts
    if not re.fullmatch(r"\d{6}", code):
        raise argparse.ArgumentTypeError("stock code must be 6 digits")
    return Position(code=code, shares=int(shares), cost=float(cost))


def cn_money(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs(value) >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.2f}"


def strength_label(q: Quote) -> str:
    if q.price >= q.high * 0.985 and q.pct >= 5:
        return "强势高位"
    if q.avg_price and q.price >= q.avg_price and q.pct > 0:
        return "均线上方"
    if q.avg_price and q.price < q.avg_price and q.pct > 0:
        return "冲高回落"
    if q.pct < -2:
        return "偏弱"
    return "中性"


def key_lines(q: Quote, pos: Position | None) -> list[str]:
    lines = []
    if pos:
        lines.append(f"成本 {pos.cost:.3f}")
    if q.avg_price:
        lines.append(f"均价 {q.avg_price:.2f}")
    lines.append(f"日高 {q.high:.2f}")
    lines.append(f"日低 {q.low:.2f}")
    lines.append(f"前收 {q.prev_close:.2f}")
    return lines


def render(quotes: dict[str, Quote], positions: dict[str, Position]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = [
        "以下是A股行情观察，不构成个性化投资建议。",
        f"时间：{now}",
        "",
    ]
    for code in sorted(quotes):
        q = quotes[code]
        pos = positions.get(code)
        out.append(f"{q.name} {q.code} [{q.source}]")
        out.append(
            f"  最新 {q.price:.2f}，涨跌 {q.change:+.2f} / {q.pct:+.2f}%"
            f"，高低 {q.high:.2f}-{q.low:.2f}，一手约 {q.lot_cash:.0f} 元"
        )
        out.append(
            f"  成交额 {cn_money(q.amount)}，换手 {q.turnover if q.turnover is not None else '-'}%"
            f"，状态：{strength_label(q)}"
        )
        if pos:
            pnl = (q.price - pos.cost) * pos.shares
            pnl_pct = (q.price / pos.cost - 1) * 100 if pos.cost else 0.0
            out.append(
                f"  持仓 {pos.shares}股，成本 {pos.cost:.3f}，浮盈亏 {pnl:+.2f} 元 / {pnl_pct:+.2f}%（未扣手续费）"
            )
        out.append(f"  关键线：{'；'.join(key_lines(q, pos))}")
        out.append("")
    return "\n".join(out).rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description="A-share realtime quote and position checker")
    parser.add_argument("codes", nargs="*", help="6-digit A-share stock codes")
    parser.add_argument(
        "-p",
        "--position",
        action="append",
        type=parse_position,
        default=[],
        help="Position as CODE:SHARES:COST, for example 000733:300:52.215",
    )
    args = parser.parse_args()

    codes = set(args.codes)
    positions = {p.code: p for p in args.position}
    codes.update(positions)
    if not codes:
        parser.error("provide at least one code or --position")

    try:
        quotes = fetch_tencent(sorted(codes))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"腾讯行情源暂不可用，切换东方财富单股备用：{exc}", file=sys.stderr)
        quotes = {}
    for code in sorted(codes - set(quotes)):
        fallback = fetch_eastmoney_one(code)
        if fallback:
            quotes[code] = fallback

    missing = sorted(codes - set(quotes))
    if missing:
        print(f"未能获取行情：{', '.join(missing)}", file=sys.stderr)
    if not quotes:
        return 2

    print(render(quotes, positions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
