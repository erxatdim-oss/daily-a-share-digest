# Daily A-Share Dynamic Digest Skill

A Codex skill for a **每日A股动态合集**: mainland China A-share market temperature, indexes, breadth, hot themes, sector rotation, 连板天梯, 龙虎榜, capital flow, announcements, risk notes, and optional watchlists.

This skill is a research aid only. It does not provide personalized investment advice, guaranteed predictions, or buy/sell instructions.

## What It Does

- Checks A-share market status, major indexes, breadth, volume, limit-up/limit-down activity, and sector rotation.
- Produces a daily A-share dynamic digest focused on hot themes, 连板天梯, 龙虎榜, capital flow, announcements, and next-session tracking points.
- Builds optional risk-aware watchlists for Shanghai/Shenzhen A-shares.
- Applies retail-account and one-lot affordability filters when users provide account constraints.
- Adds market sentiment context such as赚钱效应、热门题材、连板天梯、龙虎榜 and资金流向 when available.
- Produces bull/base/bear scenarios with invalidation conditions.
- Tracks user-provided current positions when requested.

## Install

Copy the skill folder into your Codex skills directory:

```bash
cp -R daily-a-share-digest ~/.codex/skills/
```

Restart or refresh Codex if your environment requires it.

## Example Prompts

```text
Use $daily-a-share-digest to prepare today's 每日A股动态合集 with indexes, hot themes, 连板天梯, 龙虎榜, risk notes, and optional watchlist.
```

```text
Use $daily-a-share-digest to review my current position: 000001, 100 shares, cost 10.00. Include it in today's A股动态合集.
```

## Notes

- Always cross-check live prices, announcements, and trading permissions before acting.
- Third-party market data can be delayed, unavailable, or wrong.
- If using AkShare, Tushare, or other data APIs, verify freshness and source reliability.
