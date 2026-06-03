# A股短线王

一个面向中文用户的 A 股短线研究工作台与 Codex Skill。它聚合公开行情、板块轮动、风扇/蜂巢模型、技术指标、主力动向、回测和持仓观察，帮助你做复盘、观察和风控。

本项目只做研究观察，不构成个性化投资建议，不承诺收益，也不会连接券商下单。行情源可能延迟、失败或口径不同，交易前请以券商、交易所公告和公司披露为准。

## 中文更新内容（2026-06-03）

- 项目品牌升级为 **A股短线王**，保留 skill id `daily-a-share-digest` 以兼容已安装用户。
- 分享版桌面软件改为通用默认输入：不预置任何个人持仓，所有使用者自行填写自选股、持仓和资金。
- 新增外部市场雷达：可选接入公开市场工作台风格数据，展示市场状态、主力净流入/流出、热点板块和热股排行。
- 新增回测工具：支持 MA5 上穿 MA20、MACD 金叉死叉、KDJ 低位金叉、20 日新高突破、均线 + MACD 共振等策略。
- 新增量化观察工具：做T辅助价、主力动向分、仓位管理器、交易日志和胜率/盈亏比复盘。
- 修复启动脚本路径，clone 后可直接运行 `start_daily_digest.sh` 或双击命令文件启动。

## 核心功能

- 市场温度：主要指数、交易阶段、红盘比例、强势股数量、技术均分。
- 技术指标：MACD、KDJ、RSI14、BOLL、MA5/10/20/60、量能比、技术评分。
- 风扇理论：把板块看作资金轮动的叶片，识别冷却、潜伏、启动、加速、分歧、退潮、修复。
- 蜂巢理论：把板块看作资金蜂巢，观察中期资金迁徙和拥挤度。
- 观察池：低吸观察、顺势观察、一手资金适配、单票预算和仓位上限测算。
- 持仓雷达：成本距离、浮盈亏、日内位置、止损/止盈观察线。
- 回测工具：用历史 K 线检验策略表现、最大回撤、胜率和交易明细。
- 交易复盘：记录买卖原因和结果，形成自己的交易样本。

## 安装为 Codex Skill

把项目复制到 Codex skills 目录：

```bash
cp -R daily-a-share-digest ~/.codex/skills/
```

刷新或重启 Codex 后，可继续用稳定 skill 名：

```text
Use $daily-a-share-digest to prepare today's A股短线王 digest with market sentiment, sector rotation, risk notes, and optional watchlist.
```

## 运行桌面工作台

安装依赖：

```bash
cd daily-a-share-digest
python3 -m pip install -r requirements.txt
```

启动完整工作台：

```bash
zsh start_daily_digest.sh
```

macOS 也可以双击：

```text
打开A股短线王.command
```

默认打开：

```text
http://localhost:8503
```

## 轻量可视化面板

```bash
streamlit run apps/a_share_visual_app.py
```

这个面板适合快速查看持仓、自选股、风扇叶片、蜂巢迁徙和普通主板修复扫描。

## 命令行工具

实时行情和持仓观察：

```bash
python3 scripts/a_share_watch.py -p 600000:100:10.00 000001
```

普通主板修复扫描：

```bash
python3 scripts/a_share_scan.py --pages 8 --top 30
```

## 示例提示词

```text
Use $daily-a-share-digest to prepare today's A股短线王 digest with indexes, hot themes, 连板天梯, 龙虎榜, risk notes, and optional watchlist.
```

```text
Use $daily-a-share-digest to review my current position: 000001, 100 shares, cost 10.00. Include it in today's A股短线王 research note.
```

```text
Use $daily-a-share-digest with 风扇理论 and 蜂巢理论 to analyze which A-share sectors may be repairing this week.
```

## 注意事项

- 本项目不会下单，不会读取券商账户，也不会替代持牌投顾。
- 第三方行情、外部雷达和公开 API 可能延迟或不可用。
- 回测只说明历史表现，不代表未来收益。
- 遇到 ST、退市风险、停牌、重大调查、特殊权限市场，请先做独立核验。
