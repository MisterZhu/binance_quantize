# Binance Quantize 功能文档

## 1. 产品定位

本项目是本地运行的 Binance USD-M Futures 短线量化交易工具。

- 只开放 U 本位合约自动交易。
- 默认 1x、逐仓、小仓位、强制保护止损。
- 使用 Streamlit 提供本地 Web 操作界面。

## 2. 核心页面

### 总览

显示机器人状态、市场类型、交易模式、代理、API 状态、实盘开关、自动下单状态和当前策略。

### 信号

展示最近策略信号，并支持展开单条信号的检查清单：

- 做多/做空条件是否满足
- 当前结构
- 支撑/压力
- 候选盈亏比

### 订单

展示本地记录的订单：

- 入场单
- 保护止损单
- 分批止盈单
- 移动止损撤换记录
- EMA / 结构离场市价单
- 订单状态
- 原始返回数据
- exit_plan

### 持仓

展示本地 active position：

- 当前交易对
- 方向
- 入场价
- 初始止损
- 当前止损
- 初始仓位
- 剩余仓位
- 入场单 ID
- 止损单 ID
- 分批止盈状态
- 原始执行数据

### 交易复盘

展示每笔交易的复盘摘要：

- 策略 ID / 策略名称 / 策略大类
- 方向
- 开仓价
- 平仓价
- 初始止损
- 最终止损
- 剩余仓位
- 估算 PnL
- R 倍数
- 盈亏结果
- 离场原因
- 入场检查清单
- 退出计划
- 原始订单数据

### 交易事件

展示交易生命周期事件：

- 信号入场
- 入场单提交
- 入场成交
- 保护止损挂出
- 分批止盈挂出
- 仓位数量变化
- 移动止损更新
- 策略离场
- 仓位关闭

### 风控事件

展示保护止损失败、入场单超时撤单、撤换止损失败、API 异常、风控拒绝开仓、仓位关闭识别等事件。

### 策略

支持查看内置合约策略、一键使用、复制、临时应用、另存为自定义策略。

### 交易配置

支持配置：

- futures 交易模式：dry_run / live
- 代理
- 交易币种
- 单笔风险
- 日亏损上限
- 最大仓位
- 最大连续亏损
- 保护止损

### 合约

支持配置：

- 启用合约模块
- 是否允许做空
- 保证金模式
- 杠杆
- 最大允许杠杆
- 最大名义仓位
- reduceOnly 平仓要求
- 保护止损要求
- 强平缓冲参数
- 读取合约持仓

### API 检测

只调用账户查询接口，不下单。用于验证 Key / Secret、IP 白名单、权限和代理出口。

## 3. 策略功能

当前默认策略：

- `AI推荐-合约结构突破回踩`

当前内置策略：

- 趋势突破类
  - AI推荐-合约结构突破回踩
  - AI推荐-合约稳健
  - AI推荐-合约标准
- 趋势回调类
  - AI推荐-下跌趋势反弹空
  - AI推荐-上升趋势回调多
- 日内波动回归类
  - AI推荐-VWAP/ATR 日内回归多
  - AI推荐-VWAP/ATR 日内回归空

### 入场条件

策略页会先选择策略大类，再选择该大类下的具体策略。不同大类展示不同的入场条件开关。

当前策略判断代码入口：

- `core/strategy/ema_structure.py`
- `core/strategy/support_resistance.py`
- `core/strategy/indicators.py`

文档中的“代码 key”必须和 UI 勾选项、`strategies.yaml`、`Signal.details.active_long_checks / active_short_checks` 保持一致。

### 通用计算规则

所有策略都会先把 Binance K 线转换为包含 `open/high/low/close/volume` 的 DataFrame，然后按策略参数计算 EMA。

| 参数 | 默认含义 | 代码来源 |
| --- | --- | --- |
| `ema_fast` | 快线 EMA，趋势突破默认 9 | `strategy.ema_fast` |
| `ema_mid` | 中线 EMA，默认常用 21 | `strategy.ema_mid` |
| `ema_slow` | 慢线 EMA，趋势突破默认 200，回调和回归默认 55 | `strategy.ema_slow` |
| `min_rr` | 最低盈亏比，候选 RR 小于它时不出信号 | `strategy.min_rr` |
| `min_check_score` | 最低检查项通过率，低于它时方向为 `none` | `strategy.min_check_score` |
| `level_tolerance_pct` | 接近支撑/压力/均线/VWAP/布林带的容差百分比 | `strategy.level_tolerance_pct / 100` |
| `swing_window` | 判断 swing high / swing low 时左右各比较的 K 线数量 | `strategy.swing_window` |
| `structure_lookback` | 支撑压力和结构分析最多取多少个 swing 点 | `max(12, structure_lookback * 2)` |

EMA 方向判断：

- `ema_slope_up(df, "ema21")` 的实际逻辑是：当前 EMA21 大于 3 根 K 线前的 EMA21。
- 做空里的“EMA21 向下 / 未转强”实际是 `not ema_slope_up(...)`，不是严格判断斜率连续下降。

成交量放大判断：

- 当前 K 线成交量 > 前 `volume_window` 根 K 线平均成交量 * `volume_multiplier`。

支撑压力和市场结构判断：

- `find_swings()` 会找局部 swing high / swing low。
- 最近上方 swing high 是压力 `resistance`。
- 最近下方 swing low 是支撑 `support`。
- 如果最近两个 swing high 抬高，并且最近两个 swing low 也抬高，则结构为 `up`。
- 如果最近两个 swing high 降低，并且最近两个 swing low 也降低，则结构为 `down`。
- 其他情况为 `range`，swing 数量不足为 `unknown`。

最终方向选择规则：

1. 先计算做多检查项通过率：`long_score = 做多启用项中 true 的数量 / 做多启用项总数`。
2. 再计算做空检查项通过率：`short_score = 做空启用项中 true 的数量 / 做空启用项总数`。
3. 只有合约市场且 `futures.allow_short=true` 时，做空分数才有效；否则 `short_score=0`。
4. `direction_mode=long_only` 时，强制 `short_score=0`。
5. `direction_mode=short_only` 时，强制 `long_score=0`。
6. 如果 `long_score >= short_score`，优先看做多；否则看做空。
7. 被选中的方向必须 `score >= min_check_score`，否则 `direction=none`。
8. 被选中的方向还必须 `rr >= min_rr`，否则 `direction=none`。
9. `direction=none` 时，不给 `entry_price / stop_loss / take_profit / rr`。

注意：趋势突破类当前没有在代码中单独应用 `direction_mode`，它主要依赖 `futures.allow_short` 控制做空；趋势回调类和日内回归类会应用 `direction_mode`。

### 趋势突破类

代码入口：`EmaStructureStrategy.analyze_trend_breakout()`。

默认周期：

- 大方向：`strategy.timeframes.trend`，默认 `1h`
- 确认：`strategy.timeframes.confirm`，默认 `15m`
- 入场：`strategy.timeframes.entry`，默认 `5m`

价格和 RR 计算：

- 当前价格 `price` = 入场周期最后一根 K 线 `close`。
- 做多止损 `long_stop` = 入场周期最近下方支撑；如果没有支撑，用 `price * (1 - stop_loss_pct)`。
- 做空止损 `short_stop` = 入场周期最近上方压力；如果没有压力，用 `price * (1 + stop_loss_pct)`。
- 做多止盈 `long_take` = 趋势周期最近上方压力；如果没有压力，用 `price * (1 + take_profit_pct)`。
- 做空止盈 `short_take` = 趋势周期最近下方支撑；如果没有支撑，用 `price * (1 - take_profit_pct)`。
- 做多 RR = `(long_take - price) / (price - long_stop)`，前提是 `price > long_stop`。
- 做空 RR = `(price - short_take) / (short_stop - price)`，前提是 `short_stop > price`。

做多：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 1小时：价格在 EMA200 上方 | `1h_price_above_ema200` | 趋势周期最后收盘价 > 趋势周期 EMA200 |
| 1小时：EMA21 向上 | `1h_ema21_up` | 趋势周期当前 EMA21 > 3 根 K 线前 EMA21 |
| 1小时：HH/HL 上涨结构 | `1h_hh_hl_structure` | 趋势周期结构 `structure == "up"` |
| 1小时：到下一压力有足够利润空间 | `1h_profit_space_to_resistance` | 趋势周期存在上方压力，且 `(resistance - price) / (price - long_stop) >= min_rr` |
| 15分钟：EMA9 站上 EMA21 | `15m_ema9_above_ema21` | 确认周期最后 EMA9 > EMA21 |
| 15分钟：EMA21 向上 | `15m_ema21_up` | 确认周期当前 EMA21 > 3 根 K 线前 EMA21 |
| 15分钟：成交量放大 | `15m_volume_expanded` | 确认周期最后成交量 > 前 `volume_window` 根均量 * `volume_multiplier` |
| 5分钟：突破关键压力 | `5m_breakout_resistance` | 入场周期最近 `breakout_lookback` 根最后收盘价 > 入场周期压力，且更早最多 20 根收盘价都 <= 该压力 |
| 5分钟：第一次回踩不破 | `5m_first_pullback_holds` | 入场周期最近 `pullback_lookback` 根中最低价触碰压力附近，且最后收盘价 > 该压力 |
| 综合：盈亏比满足要求 | `combined_stop_less_than_half_target` | 做多候选 RR >= `min_rr` |

做空：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 1小时：价格在 EMA200 下方 | `1h_price_below_ema200` | 趋势周期最后收盘价 < 趋势周期 EMA200 |
| 1小时：EMA21 向下 | `1h_ema21_down` | 趋势周期当前 EMA21 没有高于 3 根 K 线前 EMA21 |
| 1小时：LL/LH 下跌结构 | `1h_ll_lh_structure` | 趋势周期结构 `structure == "down"` |
| 1小时：到下一支撑有足够利润空间 | `1h_profit_space_to_support` | 趋势周期存在下方支撑，且 `(price - support) / (short_stop - price) >= min_rr` |
| 15分钟：EMA9 跌破 EMA21 | `15m_ema9_below_ema21` | 确认周期最后 EMA9 < EMA21 |
| 15分钟：EMA21 向下 | `15m_ema21_down` | 确认周期当前 EMA21 没有高于 3 根 K 线前 EMA21 |
| 15分钟：成交量放大 | `15m_volume_expanded` | 确认周期最后成交量 > 前 `volume_window` 根均量 * `volume_multiplier` |
| 5分钟：跌破关键支撑 | `5m_breakdown_support` | 入场周期最近 `breakout_lookback` 根最后收盘价 < 入场周期支撑，且更早最多 20 根收盘价都 >= 该支撑 |
| 5分钟：反弹不过，支撑变压力 | `5m_pullback_rejects_support_as_resistance` | 入场周期最近 `pullback_lookback` 根中最高价触碰支撑附近，且最后收盘价 < 该支撑 |
| 综合：盈亏比满足要求 | `combined_stop_less_than_half_target` | 做空候选 RR >= `min_rr` |

每个条件都可以在策略页面勾选启用或关闭。

### 趋势回调类

代码入口：`EmaStructureStrategy.analyze_trend_pullback()`。

默认周期：

- 大趋势：`strategy.timeframes.trend`，默认 `4h`
- 回调确认：`strategy.timeframes.confirm`，默认 `1h`
- 入场：`strategy.timeframes.entry`，默认 `5m`

价格和 RR 计算：

- 当前价格 `price` = 入场周期最后一根 K 线 `close`。
- 确认周期会额外计算 VWAP。
- 做多止损 `long_stop` = 入场周期支撑；没有则用确认周期支撑；再没有则用 `price * (1 - stop_loss_pct)`。
- 做空止损 `short_stop` = 入场周期压力；没有则用确认周期压力；再没有则用 `price * (1 + stop_loss_pct)`。
- 做多止盈 `long_take` = 确认周期压力；没有则用趋势周期压力；再没有则用 `price * (1 + take_profit_pct)`。
- 做空止盈 `short_take` = 确认周期支撑；没有则用趋势周期支撑；再没有则用 `price * (1 - take_profit_pct)`。

上升趋势回调多：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 大周期：上升趋势成立 | `pullback_long_trend_up` | 趋势周期最后收盘价 > 慢线 EMA，且趋势周期中线 EMA 向上，且趋势结构 `structure == "up"`；内置回调策略默认慢线 EMA55、中线 EMA21 |
| 回调：接近支撑/均线/VWAP | `pullback_long_near_support_or_ema` | 当前价格接近确认周期中线 EMA、慢线 EMA、确认周期支撑或 VWAP 中任意一个，容差为 `level_tolerance_pct`；内置回调策略默认 EMA21 / EMA55 |
| 入场：重新站上 EMA9 | `pullback_long_entry_reclaims_ema9` | 入场周期最后收盘价 > EMA9，且最后收盘价 > 最后开盘价 |
| 确认：EMA21 未转弱 | `pullback_long_confirm_ema21_not_down` | 确认周期当前 EMA21 > 3 根 K 线前 EMA21 |
| 综合：回调多盈亏比满足 | `pullback_long_rr_ok` | 做多候选 RR >= `min_rr` |

下跌趋势反弹空：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 大周期：下跌趋势成立 | `pullback_short_trend_down` | 趋势周期最后收盘价 < 慢线 EMA，且趋势周期中线 EMA 没有向上，且趋势结构 `structure == "down"`；内置回调策略默认慢线 EMA55、中线 EMA21 |
| 反弹：接近压力/均线/VWAP | `pullback_short_near_resistance_or_ema` | 当前价格接近确认周期中线 EMA、慢线 EMA、确认周期压力或 VWAP 中任意一个，容差为 `level_tolerance_pct`；内置回调策略默认 EMA21 / EMA55 |
| 入场：跌回 EMA9 下方 | `pullback_short_entry_loses_ema9` | 入场周期最后收盘价 < EMA9，且最后收盘价 < 最后开盘价 |
| 确认：EMA21 未转强 | `pullback_short_confirm_ema21_not_up` | 确认周期当前 EMA21 没有高于 3 根 K 线前 EMA21 |
| 综合：反弹空盈亏比满足 | `pullback_short_rr_ok` | 做空候选 RR >= `min_rr` |

### 日内波动回归类

代码入口：`EmaStructureStrategy.analyze_intraday_mean_reversion()`。

默认周期：

- 环境观察：`strategy.timeframes.trend`，默认 `1h`
- 回归判断：`strategy.timeframes.confirm`，默认 `15m`
- 入场：`strategy.timeframes.entry`，默认 `5m`

确认周期会计算：

- VWAP
- ATR14
- 布林带：20 周期均线，2 倍标准差，上轨 `bb_upper`，中轨 `bb_mid`，下轨 `bb_lower`

价格和 RR 计算：

- 当前价格 `price` = 入场周期最后一根 K 线 `close`。
- `atr_pct = ATR14 / price`。
- `vwap_deviation = (price - vwap) / vwap`。
- 做多止损 `long_stop` = 入场周期支撑；没有则取 `min(布林下轨, price * (1 - stop_loss_pct))`。
- 做空止损 `short_stop` = 入场周期压力；没有则取 `max(布林上轨, price * (1 + stop_loss_pct))`。
- 做多止盈 `long_take` = 如果 `min(VWAP, 布林中轨) > price`，则取 `min(VWAP, 布林中轨)`；否则取 `price * (1 + take_profit_pct)`。
- 做空止盈 `short_take` = 如果 `max(VWAP, 布林中轨) < price`，则取 `max(VWAP, 布林中轨)`；否则取 `price * (1 - take_profit_pct)`。

日内回归多：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 日内：波动率足够 | `reversion_long_volatility_enough` | `atr_pct >= mean_reversion_min_atr_pct / 100` |
| 位置：价格明显低于 VWAP | `reversion_long_below_vwap` | `vwap_deviation <= -mean_reversion_min_vwap_deviation_pct / 100` |
| 位置：接近布林下轨 | `reversion_long_near_lower_band` | 当前价格 <= 布林下轨，或按 `level_tolerance_pct` 接近布林下轨 |
| 入场：5分钟止跌转强 | `reversion_long_entry_reversal` | 入场周期最后收盘价 > 最后开盘价，且最后收盘价 > EMA9 |
| 目标：回到 VWAP 盈亏比满足 | `reversion_long_target_to_vwap_ok` | 做多候选 RR >= `min_rr` |

日内回归空：

| UI 文案 | 代码 key | 实际判断 |
| --- | --- | --- |
| 日内：波动率足够 | `reversion_short_volatility_enough` | `atr_pct >= mean_reversion_min_atr_pct / 100` |
| 位置：价格明显高于 VWAP | `reversion_short_above_vwap` | `vwap_deviation >= mean_reversion_min_vwap_deviation_pct / 100` |
| 位置：接近布林上轨 | `reversion_short_near_upper_band` | 当前价格 >= 布林上轨，或按 `level_tolerance_pct` 接近布林上轨 |
| 入场：5分钟冲高转弱 | `reversion_short_entry_reversal` | 入场周期最后收盘价 < 最后开盘价，且最后收盘价 < EMA9 |
| 目标：回到 VWAP 盈亏比满足 | `reversion_short_target_to_vwap_ok` | 做空候选 RR >= `min_rr` |

### 当前内置策略参数差异

| 策略 | family | direction_mode | 周期 | min_rr | min_check_score | 主要差异 |
| --- | --- | --- | --- | --- | --- | --- |
| AI推荐-合约结构突破回踩 | `trend_breakout` | `both` | 1h / 15m / 5m | 2.0 | 0.85 | 默认趋势突破模板，所有趋势突破检查项默认启用 |
| AI推荐-合约稳健 | `trend_breakout` | `both` | 1h / 15m / 5m | 2.5 | 0.9 | 更高 RR、更严格成交量，交易频率更低 |
| AI推荐-合约标准 | `trend_breakout` | `both` | 1h / 15m / 5m | 2.0 | 0.85 | 比默认模板结构 lookback 更短，止损比例略小 |
| AI推荐-下跌趋势反弹空 | `trend_pullback` | `short_only` | 4h / 1h / 5m | 1.6 | 0.8 | 只做下跌趋势里的反弹空 |
| AI推荐-上升趋势回调多 | `trend_pullback` | `long_only` | 4h / 1h / 5m | 1.6 | 0.8 | 只做上升趋势里的回调多 |
| AI推荐-VWAP/ATR 日内回归多 | `intraday_mean_reversion` | `long_only` | 1h / 15m / 5m | 1.3 | 0.8 | 只做低于 VWAP 和接近布林下轨后的回归多 |
| AI推荐-VWAP/ATR 日内回归空 | `intraday_mean_reversion` | `short_only` | 1h / 15m / 5m | 1.3 | 0.8 | 只做高于 VWAP 和接近布林上轨后的回归空 |

以上策略只是代码内置模板，不代表已经经过回测验证。后续优化策略时，建议先修改本章节的条件描述和参数意图，再让 AI 对照实现代码、UI、`strategies.yaml` 和复盘字段。

## 4. 退出策略

当前已支持两类退出模式：

- 分批止盈 + 移动止损
- 移动止损

移动止损方法包括：

- 按 R 倍数移动
- 跟随 EMA
- 跟随前低/前高
- 跟随结构位

当前已接入真实订单的退出能力：

- 开仓成交后立即挂保护止损单
- 分批止盈 reduceOnly 限价单
- 有 active position 时只管理仓位，不再开新仓
- R 倍数移动止损会撤换 STOP_MARKET
- EMA 跟随离场会触发 reduceOnly 市价平仓
- 结构离场会触发 reduceOnly 市价平仓

强平缓冲、成交回填和 trades 统计仍需继续增强。

### 分批止盈 + 移动止损

适合先锁定部分利润，同时保留一部分仓位让趋势继续运行。

当前默认逻辑：

1. 根据入场价和初始止损计算 1R。
2. 按策略配置挂多个 reduceOnly 限价止盈单。
3. 剩余 runner 仓位不挂固定止盈，交给移动止损或趋势离场规则处理。
4. 后续循环通过交易所持仓数量更新本地 remaining_amount。

### 移动止损

适合不预设分批止盈，主要通过跟随趋势离场。

当前支持：

- R 倍数移动：达到指定 R 后，把止损推进到保本或更高利润位置。
- EMA 跟随：价格跌破或突破指定 EMA 后离场；周期可在策略页手动选择，默认 15m EMA21。
- 前低/前高跟随：根据 swing 结构判断趋势是否破坏。
- 结构位跟随：根据 5 分钟结构位判断离场。

## 5. 保护止损

开仓流程：

1. 提交入场单。
2. 如果是限价单，等待成交。
3. 成交后按实际成交数量创建保护止损单。
4. 超时未成交则撤销入场单。
5. 保护止损失败则记录 critical 风控事件。
6. 如果 `required=true`，保护止损失败会中止流程。

合约保护单：

- `STOP_MARKET`
- `reduceOnly=true`
- `workingType=MARK_PRICE`

如果挂保护止损失败，并且 `execution.protective_stop.required=true`，本轮执行会抛错并记录 critical 风控事件。此时需要人工检查是否已有裸露仓位。

## 6. 持仓状态机

机器人循环不是“无限开新单”。当前规则是单仓位优先：

```text
发现 active position:
  查询 Binance 合约持仓
  如果交易所仓位已归零，标记本地仓位 closed
  如果仓位仍存在，更新 remaining_amount
  检查 EMA/结构离场
  检查 R 倍数移动止损
  本轮不扫描新入场

没有 active position:
  扫描行情和策略信号
  风控通过后下入场单
  成交后挂保护止损和分批止盈
  写入 active_positions
```

## 7. 当前限制

- 分批止盈订单成交后的精确剩余仓位回填依赖交易所持仓查询。
- 强平价距离检查仍需进一步接入持仓数据。
- 未使用 WebSocket 订单推送，订单状态依赖循环查询。
- `trade_journal` 已提供第一版复盘摘要，但手续费、逐笔成交、精确均价仍待完整回填。
- VWAP/ATR 日内回归策略仍未经过本地回测验证。
- 尚未实现完整回测和参数优化。
