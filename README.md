# A-Share Daily Research Skill

A Codex skill for daily mainland China A-share market research, sector rotation notes, watchlists, and scenario-based risk analysis.

This skill is a research aid only. It does not provide personalized investment advice, guaranteed predictions, or buy/sell instructions.

## What It Does

- Checks A-share market status, major indexes, breadth, volume, and sector rotation.
- Builds risk-aware watchlists for Shanghai/Shenzhen A-shares.
- Applies retail-account and one-lot affordability filters when users provide account constraints.
- Adds market sentiment context such as赚钱效应、热门题材、连板天梯、龙虎榜 and资金流向 when available.
- Produces bull/base/bear scenarios with invalidation conditions.
- Tracks user-provided current positions when requested.

## Install

Copy the `a-share-daily-research` folder into your Codex skills directory:

```bash
cp -R a-share-daily-research ~/.codex/skills/
```

Restart or refresh Codex if your environment requires it.

## Example Prompts

```text
Use $a-share-daily-research to prepare today's A股 observation list. I use 同花顺, have about 3000 CNY cash, and do not have 科创板 or 北交所 permissions.
```

```text
Use $a-share-daily-research to review my current position: 000001, 100 shares, cost 10.00. Give next-session scenarios and risk levels.
```

## Notes

- Always cross-check live prices, announcements, and trading permissions before acting.
- Third-party market data can be delayed, unavailable, or wrong.
- If using AkShare, Tushare, or other data APIs, verify freshness and source reliability.
