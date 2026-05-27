# Daily A-Share Dynamic Digest Skill

A Codex skill for a **每日A股动态合集**: mainland China A-share market temperature, indexes, breadth, hot themes, sector rotation, 连板天梯, 龙虎榜, capital flow, announcements, risk notes, and optional watchlists.

This skill is a research aid only. It does not provide personalized investment advice, guaranteed predictions, or buy/sell instructions.

## 中文更新内容（2026-05-27）

- 加入 **风扇理论**：把板块当作电风扇叶片，观察资金在冷却、潜伏、启动、加速、高潮、分歧、退潮、修复之间轮动。
- 加入 **蜂巢理论**：把板块当作蜂蜜格、主力资金当作蜜蜂，用近半年/中期数据判断资金可能迁徙到哪些板块。
- 加入普通账户友好的 A 股筛选逻辑：默认排除科创板、北交所、创业板、ST、退市风险、ETF、可转债等特殊权限或高风险品种。
- 加入修复/低吸观察框架：不是“跌得多就买”，而是看止跌、站回均价/短均线、成交承接和失效线。
- 打包两个命令行工具：实时持仓观察 `scripts/a_share_watch.py` 和普通主板修复扫描 `scripts/a_share_scan.py`。
- 新增 Mac 可视化面板：`apps/a_share_visual_app.py`，可查看持仓、自选股、风扇叶片、蜂巢迁徙和修复扫描。

## What It Does

- Checks A-share market status, major indexes, breadth, volume, limit-up/limit-down activity, and sector rotation.
- Produces a daily A-share dynamic digest focused on hot themes, 连板天梯, 龙虎榜, capital flow, announcements, and next-session tracking points.
- Builds optional risk-aware watchlists for Shanghai/Shenzhen A-shares.
- Applies retail-account and one-lot affordability filters when users provide account constraints.
- Adds market sentiment context such as赚钱效应、热门题材、连板天梯、龙虎榜 and资金流向 when available.
- Adds 风扇理论 and 蜂巢理论 sections for sector-cycle and capital-migration analysis.
- Produces bull/base/bear scenarios with invalidation conditions.
- Tracks user-provided current positions when requested.

## Install

Copy the skill folder into your Codex skills directory:

```bash
cp -R daily-a-share-digest ~/.codex/skills/
```

Restart or refresh Codex if your environment requires it.

## Mac 可视化软件

Install dependencies:

```bash
cd daily-a-share-digest
python3 -m pip install -r requirements.txt
```

Run the dashboard:

```bash
streamlit run apps/a_share_visual_app.py
```

It opens in your browser and includes:

- 持仓与自选：输入 `代码 股数 成本`，查看实时价格、浮盈亏、一手资金。
- 风扇/蜂巢：用代表股观察板块叶片状态和资金迁徙方向。
- 修复扫描：扫描普通沪深主板，寻找修复/低吸观察池。

Public quote endpoints may be delayed or temporarily unavailable. Always verify with your broker before trading.

## Scripts

Realtime quote and position check:

```bash
python3 scripts/a_share_watch.py -p 600487:200:68.82 000758
```

Ordinary-main-board repair scan:

```bash
python3 scripts/a_share_scan.py --pages 8 --top 30
```

## Example Prompts

```text
Use $daily-a-share-digest to prepare today's 每日A股动态合集 with indexes, hot themes, 连板天梯, 龙虎榜, risk notes, and optional watchlist.
```

```text
Use $daily-a-share-digest to review my current position: 000001, 100 shares, cost 10.00. Include it in today's A股动态合集.
```

```text
Use $daily-a-share-digest with 风扇理论 and 蜂巢理论 to analyze which A-share sectors may be repairing this week.
```

## Notes

- Always cross-check live prices, announcements, and trading permissions before acting.
- Third-party market data can be delayed, unavailable, or wrong.
- If using AkShare, Tushare, or other data APIs, verify freshness and source reliability.
