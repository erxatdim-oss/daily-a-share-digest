---
name: a-share-daily-research
description: Use when preparing daily A-share market research, China stock watchlists, sector rotation notes, risk-aware stock screening, or scenario-based forecasts for mainland China equities. Triggers for requests about 国内股票, A股, 沪深京股票, 每日荐股, 股票观察清单, 资金流向, 板块轮动, 连板天梯, 龙虎榜, or next-session stock research. This skill must not present personalized investment advice or guaranteed predictions.
---

# A-Share Daily Research

Use this skill to produce a daily A股 research brief and watchlist. The output is a research aid, not personalized financial advice.

## Safety Rules

- Do not promise returns, use deterministic language like "必涨", or claim to predict exact prices.
- Do not tell the user to buy, sell, hold, add leverage, all-in, or trade at any exact price as a directive.
- Label candidates as "观察标的" or "候选池", not "must-buy recommendations".
- Include risk notes, invalidation conditions, and why the idea may fail.
- If the user asks for personal allocation, portfolio construction, suitability advice, or account-specific trade sizing, explain that this requires a licensed adviser and provide only general education.
- For current market data, news, rules, or prices, browse or use live data tools before answering.
- Treat rumors, social-media posts, and forum claims as unverified unless confirmed by company announcements, exchange disclosures, official filings, or reputable media.

## User Constraints

Ask for or infer constraints before narrowing the watchlist:

- Broker/app access, such as 同花顺, 东方财富, or a specific securities account.
- Approximate cash scale and whether the user wants one-lot affordability filters.
- Confirmed permissions, such as 创业板, 科创板, 北交所, 港股通, options, margin trading, or fund products.
- Current positions and cost basis if the user wants position checks.
- Risk preference: conservative, balanced, aggressive, or short-term momentum.

If the user gives no constraints, default to ordinary Shanghai/Shenzhen main-board A-shares and avoid special-permission markets.

## Retail Account And Budget Filter

When the user mentions a small cash budget or ordinary retail account, apply this default filter unless the user says otherwise:

- Assume the user can place ordinary A-share orders through their broker app, but do not assume special permissions.
- Prefer Shanghai/Shenzhen main-board A-shares that a normal retail account can usually access.
- Exclude 科创板, 北交所, margin/short candidates, B-shares, 港股通, ETFs, convertible bonds, and other products unless explicitly requested.
- Exclude 创业板 if the user has not confirmed they have 创业板 permission.
- Exclude ST/*ST, delisting-risk names, suspended names, names under major investigation, and obvious liquidity traps.
- A-share buy orders are commonly in 100-share lots. For small accounts, show "一手约需资金 = 最新价 x 100" for every candidate.
- Mark candidates that would consume most of the user's cash as "资金集中风险".
- If fewer than 3 quality candidates pass the filter, say so and provide fewer names rather than lowering risk controls.

## Market Sentiment Add-On

When available, incorporate A-share short-term sentiment data before ranking candidates:

- Earning effect: market breadth, limit-up/limit-down count, fried-board rate, advancing vs declining names.
- Theme heat: top concepts/industries by涨幅, turnover, and persistence from morning to afternoon.
- 连板天梯 and high-board names: use them to judge whether risk appetite is expanding or contracting.
- 龙虎榜 and institutional/游资 clues: only use as supporting evidence, not a buy signal by itself.
- Capital flow: compare individual stock volume/turnover with sector heat; flag放量滞涨 and冲高回落.
- Trading calendar: distinguish trading days, holidays, pre-market, intraday, lunch break, and post-close.

The GitHub project `Niceck/hhxg-top-hhxg-python` can be used as a reference for market-sentiment categories such as赚钱效应、热门题材、连板天梯、龙虎榜、行业资金、财经快讯、融资融券、交易日历. Treat third-party data as unverified until cross-checked with Eastmoney, Tonghuashun, Sina Finance, exchange announcements, or company filings.

## Daily Workflow

1. Confirm date, market status, and whether A股 is open. Note if the brief is pre-market, intraday, lunch break, post-close, weekend, or holiday.
2. Gather current sources:
   - Official exchanges and regulators: SSE, SZSE, BSE, CSRC.
   - Company filings and announcements: 巨潮资讯, exchange announcements, company investor relations pages.
   - Market data portals: Eastmoney, Tonghuashun, Sina Finance, Tencent Finance, Wind-like summaries when accessible.
   - News and catalysts: 证券时报, 财联社, 上海证券报, 中国证券报, official policy releases.
   - Optional quantitative data: AkShare or Tushare if available locally; verify freshness before trusting it.
3. Build market context:
   - Major index trend: 上证指数, 深证成指, 创业板指, 科创50, 北证50.
   - Breadth: 涨跌家数, 涨停/跌停, 量能 vs recent average.
   - Northbound/ETF/fund flow when available.
   - Sector rotation and policy/event catalysts.
4. Check current positions when the user provides them:
   - Current price vs cost basis.
   - Key support/resistance and invalidation levels.
   - Strong/base/weak next-session scenarios.
   - Whether new candidates duplicate existing portfolio exposure.
5. Screen candidates with multiple, independent signals:
   - Liquidity: avoid thinly traded names unless explicitly requested.
   - Momentum: recent relative strength vs index and sector.
   - Volume/price confirmation: breakout, reversal, or consolidation with clear invalidation.
   - Fundamentals: profitability, revenue trend, valuation, balance-sheet stress, pledge or delisting risk.
   - Catalysts: policy, earnings, order wins, industry events, announcements.
   - Risk filters: ST/*ST, regulatory investigation, abnormal volatility, imminent lockup expiry, large shareholder reduction, repeated failed breakouts.
   - Accessibility and budget: apply the user's retail account and one-lot affordability filter when relevant.
6. Rank with a transparent score, not a black box:
   - Trend and relative strength: 25%
   - Volume and capital attention: 20%
   - Catalyst clarity: 20%
   - Fundamental/valuation support: 20%
   - Risk control quality: 15%
7. Forecast only as scenarios:
   - Bull/base/bear paths for the next session or next 3-5 trading days.
   - Assign rough probabilities only if evidence supports them.
   - State invalidation signals such as sector breakdown, index volume failure, announcement risk, or key support loss.

## Output Format

Write in Chinese unless the user asks otherwise.

Start with this disclaimer:
"以下是A股研究观察清单，不构成个性化投资建议。"

Then provide:

1. **市场温度**: date, status, broad index read, breadth, volume, dominant sectors.
2. **今日主线**: 2-4 sector/catalyst themes with why they matter.
3. **持仓检查**: only if the user provided positions; include current price, cost line, support, failure line, and next-session scenarios.
4. **观察清单**: 3-8 stocks max, each with:
   - 股票名称 + 代码
   - 所属行业/概念
   - 最新价, 一手约需资金, and whether it fits the user's stated cash budget
   - 关注理由, using current evidence
   - 情景推演: 强/中/弱 path
   - 风险与失效条件
   - 观察级别: 高/中/低, based on evidence quality
5. **不碰清单**: obvious risks or overheated areas.
6. **下个交易日跟踪点**: 3-5 concrete signals to verify.

Keep it concise, source-backed, and timestamped. Link the most important sources when browsing was used.

## Recommended Sources To Check

- 上海证券交易所: https://www.sse.com.cn/
- 深圳证券交易所: https://www.szse.cn/
- 北京证券交易所: https://www.bse.cn/
- 中国证监会: https://www.csrc.gov.cn/
- 巨潮资讯: https://www.cninfo.com.cn/
- 东方财富: https://www.eastmoney.com/
- 同花顺财经: https://www.10jqka.com.cn/
- 新浪财经: https://finance.sina.com.cn/
- 财联社: https://www.cls.cn/
- AkShare docs: https://akshare.akfamily.xyz/
- Tushare docs: https://tushare.pro/document/2
