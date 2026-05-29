# Daily A-Share Dynamic Digest Skill

A Codex skill for a **每日A股动态合集**: mainland China A-share market temperature, indexes, breadth, hot themes, sector rotation, 连板天梯, 龙虎榜, capital flow, announcements, risk notes, and optional watchlists.

This skill is a research aid only. It does not provide personalized investment advice, guaranteed predictions, or buy/sell instructions.

## 中文更新内容（2026-05-28）

- 新增可分享版 Mac 软件：`apps/daily_a_share_digest_app.py`，并提供 `start_daily_digest.sh` 与 `打开A股每日动态合集.command`。
- 分享版已改为通用默认输入：不预置任何个人持仓，所有使用者自行填写自己的代码/仓位。
- 重大 UI 升级：简约交易终端风格，包含市场状态条、交易员信号队列、观察窗口、技术指标矩阵和可复制文本合集。
- 新增技术指标引擎：MACD、KDJ、RSI14、BOLL、MA5/10/20/60、量能比、技术评分。
- 新增并发指标计算：多只股票同步拉取日 K，减少打开等待时间。
- 修复历史日 K 接口参数，确保 MACD/KDJ 等指标可以稳定计算。
- 分享版启动脚本会优先使用本机已有环境；没有环境时，会在软件目录下自动创建 `.venv` 并安装依赖。

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

## 分享版桌面软件

这个仓库还包含一个更完整的本地桌面面板：

```bash
zsh start_daily_digest.sh
```

macOS 用户也可以双击：

```text
打开A股每日动态合集.command
```

它会启动 `apps/daily_a_share_digest_app.py`，默认打开：

```text
http://localhost:8503
```

功能包括：

- 自选池与持仓账本。
- 市场状态、主线叶片、红盘比例、强势股数、技术均分。
- MACD/KDJ/RSI/BOLL/均线/量能比/技术评分。
- 风扇理论板块轮动与蜂巢资金迁徙。
- 观察池、持仓雷达、文本版每日动态合集。

首次运行需要本机有 `python3`。如果没有可用 Streamlit 环境，脚本会自动创建 `.venv` 并安装 `requirements.txt`。

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
