# Binance Quantize 技术文档

## 1. 技术栈

- Python 3.12
- Streamlit
- ccxt
- pandas / numpy
- plotly
- SQLite
- PyYAML
- python-dotenv
- loguru

## 2. 目录结构

```text
binance_quantize/
  app.py
  bot_runner.py
  check_auth.py
  check_network.py
  config.yaml
  strategies.yaml
  core/
    exchange/
    execution/
      exit_manager.py
      order_manager.py
      position_manager.py
    risk/
    storage/
    strategy/
    utils/
  data/
  docs/
  logs/
```

## 3. 模块与核心类说明

本项目是单体本地应用，UI、机器人循环、策略、执行和 SQLite 持久化都在同一个仓库内。代码按业务层次拆分，优先保持模块边界清晰。

### 根目录入口

| 文件 | 职责 | 修改注意 |
| --- | --- | --- |
| `app.py` | Streamlit 本地界面，负责展示信号、订单、持仓、策略配置、交易配置和复盘数据。 | UI 文案默认中文；改策略配置 UI 时要同步 `strategies.yaml` 和配置加载逻辑。 |
| `bot_runner.py` | 自动机器人循环入口。无仓位时扫描信号，有仓位时只执行持仓退出管理。 | 不要绕过 `RiskManager` 和保护止损流程。 |
| `check_auth.py` | Binance API 认证检测，只查账户，不下单。 | 不输出完整 API Key。 |
| `check_network.py` | 网络和代理连通性检测。 | 主要用于中国地区/VPN/代理排查。 |
| `config.yaml` | 运行配置，包括交易所、交易对、风险、合约、执行和 API 限速。 | 当前产品方向是 futures-first。 |
| `strategies.yaml` | 策略库，包含内置策略、当前策略、入场条件和退出参数。 | 内置策略不可直接修改，UI 应复制后另存为自定义策略。 |

### `core/exchange`

封装 Binance / ccxt 访问，避免业务层直接操作 ccxt。

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `client.py` / `BinanceClient` | 创建 ccxt Binance client，加载市场、获取 K 线、查询余额/订单/持仓、下单、设置合约安全参数。 | `create_order()` 内置 dry_run/live 双模式；live 下单必须设置 `ENABLE_LIVE_TRADING=true`。 |
| `auth_check.py` | API Key、Secret、IP 白名单和权限检测。 | 只调用账户查询接口，不负责下单。 |

### `core/strategy`

负责从多周期 K 线生成交易信号，只输出结构化 `Signal`，不负责下单。

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `ema_structure.py` / `Signal` | 策略输出数据结构，包含方向、价格、止损、止盈、RR 和 checklist 细节。 | `direction="none"` 表示不可交易。 |
| `ema_structure.py` / `EmaStructureStrategy` | 主策略引擎，根据策略大类生成趋势突破、趋势回调、日内回归信号。 | 读取 `strategy.family`、`direction_mode`、条件开关和阈值参数。 |
| `indicators.py` | EMA、VWAP、ATR、布林带、成交量放大、接近关键位等指标。 | 只做指标计算，避免写入交易决策副作用。 |
| `support_resistance.py` / `StructureLevels` | swing high/low、支撑压力、HH/HL、LL/LH、突破、回踩、利润空间。 | 趋势突破策略高度依赖这里的结构判断。 |
| `market_structure.py` | 市场结构相关辅助逻辑。 | 后续扩展结构识别时优先放这里或 `support_resistance.py`。 |

### `core/risk`

负责下单前的硬性风险过滤和仓位计算。

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `manager.py` / `RiskDecision` | 风控结果结构，说明是否允许开仓、拒绝原因和下单数量。 | 拒绝原因会影响 UI 和复盘排查。 |
| `manager.py` / `RiskManager` | 检查机器人状态、已有持仓、止损、RR、合约开关、做空开关、杠杆上限和最大仓位。 | 计算公式为 `risk_budget / abs(entry - stop)`，再受最大名义金额限制。 |

### `core/execution`

负责真实订单生命周期，是风险最高的模块。修改这里必须保持保护止损和 reduceOnly 语义。

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `order_manager.py` / `OrderManager` | 执行入场信号，等待成交，立即挂保护止损，挂分批止盈，创建 active position 和 trade journal。 | live 自动交易的底线是开仓后必须有保护止损；保护止损失败默认抛错。 |
| `exit_manager.py` / `ExitPlan` | 退出计划数据结构，记录初始止损、分批止盈目标和移动止损规则。 | 不访问交易所，只描述计划。 |
| `exit_manager.py` | 计算分批止盈、R 倍数移动止损、EMA 跟随离场和结构离场。 | 真实撤单/下单由 `PositionManager` 执行。 |
| `position_manager.py` / `PositionManager` | 管理已有仓位，查询交易所真实持仓，识别仓位关闭，更新剩余数量，执行 EMA/结构离场和移动止损撤换。 | 有 active position 时，主循环不再扫描新入场。 |

### `core/storage`

负责 SQLite 持久化，给 UI、机器人和 AI 复盘共用。

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `database.py` / `Database` | 初始化 SQLite 表，写入信号、订单、风险事件、active position、trade journal 和 trade events。 | `data/trader.sqlite` 被 git 忽略；不要把数据库提交到仓库。 |
| `database.py` / `utc_now()` | 统一生成 UTC ISO 时间。 | 复盘和清理脚本依赖时间字段。 |

### `core/utils`

| 文件 / 类 | 职责 | 关键点 |
| --- | --- | --- |
| `config.py` | 加载 `config.yaml`、`strategies.yaml` 和 `data/runtime_strategy.yaml`，并按优先级合并配置。 | 优先级：基础配置 < 当前策略 < 临时策略覆盖。 |
| `logger.py` | loguru 日志初始化。 | 不记录敏感信息。 |

## 4. 关键调用链路

### 无仓位时：信号到开仓

```text
bot_runner.py / app.py
  -> BinanceClient.fetch_ohlcv()
  -> EmaStructureStrategy.analyze()
  -> Database.insert_signal()
  -> RiskManager.evaluate()
  -> OrderManager.execute_signal()
  -> BinanceClient.create_order()
  -> OrderManager._wait_for_entry_fill()
  -> OrderManager._create_protective_stop()
  -> OrderManager._create_partial_take_profit_orders()
  -> Database.upsert_active_position()
  -> Database.create_trade_journal()
  -> Database.insert_trade_event()
```

### 有仓位时：退出管理

```text
bot_runner.py / app.py
  -> Database.get_active_position()
  -> PositionManager.manage_active_position()
  -> BinanceClient.fetch_positions()
  -> PositionManager 同步 remaining_amount
  -> ExitManager 规则函数判断 EMA/结构离场
  -> BinanceClient.create_order(reduceOnly=true) 平仓
  -> 或撤换 STOP_MARKET 移动止损
  -> Database.update_active_position()
  -> Database.update_trade_journal()
  -> Database.insert_trade_event()
```

### 交易复盘导出

```text
data/trader.sqlite
  -> .codex/skills/trade-review/scripts/export_trade_review.py
  -> data/exports/trade_review/trade_review_latest.jsonl
  -> data/exports/trade_review/trade_stats_latest.csv
  -> data/exports/trade_review/trade_review_report.md
```

## 5. 修改风险提示

- 改 `OrderManager`、`PositionManager`、`BinanceClient.create_order()` 前，必须确认不会产生裸仓。
- 改 `RiskManager` 前，必须确认仓位、RR、止损和杠杆限制仍然生效。
- 改 `EmaStructureStrategy` 前，必须同步 UI 中文 checklist、`strategies.yaml` 默认参数和文档。
- 改 `Database` 表结构后，需要兼容已有 SQLite 文件，因为用户本地可能已有历史数据。
- 改配置合并逻辑后，需要确认 `config.yaml`、`strategies.yaml`、`runtime_strategy.yaml` 的优先级不变。

## 6. 配置模型

### config.yaml

用于运行级配置：

- exchange
- symbols
- risk
- futures
- execution
- api_limits

当前固定：

```yaml
exchange:
  market_type: futures
```

### strategies.yaml

用于合约策略模板：

- active_strategy
- strategies
- params.strategy
- params.execution
- params.exit

内置策略不可直接修改，自定义策略可保存。

### data/runtime_strategy.yaml

用于临时策略覆盖。点击“临时应用本次参数”后写入，不进入策略库。

## 7. 配置加载

入口：

- `core/utils/config.py`

流程：

1. 读取 `config.yaml`
2. 读取 `strategies.yaml`
3. 应用 active_strategy 参数
4. 如果存在 `data/runtime_strategy.yaml`，再应用临时参数

## 8. Binance 接入

入口：

- `core/exchange/client.py`

职责：

- 创建 ccxt Binance client
- futures defaultType
- 支持代理
- 获取 K 线
- 查询余额
- 查询订单
- 查询合约持仓
- 下单
- 设置合约杠杆和保证金模式

行情加载禁用 `fetchCurrencies`，避免 ccxt 在有 API Key 时额外调用权限相关接口。

## 9. 策略模块

### 指标

- `core/strategy/indicators.py`

提供 EMA、VWAP、ATR、布林带、成交量放大和价格接近关键位等基础计算。

### 支撑压力和结构

- `core/strategy/support_resistance.py`

负责 swing high / swing low、HH/HL、LL/LH、支撑压力、突破/跌破、第一次回踩和利润空间。

### 策略引擎

- `core/strategy/ema_structure.py`

负责多周期行情准备、按策略大类生成做多/做空 checklist、按启用检查项计算 score、生成 signal、计算结构止损和 RR。

策略通过 `strategy.family` 分流：

- `trend_breakout`: 趋势突破类，保留原多周期突破/跌破和回踩确认逻辑。
- `trend_pullback`: 趋势回调类，等待大趋势内的回调/反弹到均线、支撑压力或 VWAP 附近，再用小周期确认。
- `intraday_mean_reversion`: 日内波动回归类，使用 VWAP、ATR 和布林带判断价格日内偏离，目标吃回归 VWAP / 中位线的一段。

策略通过 `strategy.direction_mode` 限定方向：

- `both`
- `long_only`
- `short_only`

后续可新增策略自动选择器，根据趋势强度、VWAP 偏离、ATR 波动和区间结构，在三类策略之间给出推荐或自动切换；当前版本仍由用户手动选择策略。

## 10. 风控模块

入口：

- `core/risk/manager.py`

检查：

- 是否有信号
- 机器人是否 running
- 是否有止损
- RR 是否满足
- futures enabled
- allow_short
- leverage <= max_leverage
- 最大仓位限制

仓位计算：

```text
risk_budget = equity * risk_per_trade_pct
amount = risk_budget / abs(entry - stop)
amount <= max_position_usdt / entry
```

## 11. 执行模块

### OrderManager

- `core/execution/order_manager.py`

职责：

- 提交入场单
- 等待限价单成交
- 未成交撤单
- 成交后创建保护止损单
- 成交后创建分批止盈限价单
- 写入 active_positions
- 记录订单
- 记录 critical 风控事件

合约保护止损：

```text
STOP_MARKET
reduceOnly=true
workingType=MARK_PRICE
```

分批止盈单：

```text
limit
reduceOnly=true
timeInForce=GTC
```

### ExitManager

- `core/execution/exit_manager.py`

职责：

- 生成 exit_plan
- 计算移动止损
- 判断 EMA 跟随离场
- 判断结构离场
- 生成分批止盈目标

ExitManager 只负责计划和规则计算，不直接访问交易所。真实订单动作由 OrderManager 和 PositionManager 执行。

退出配置结构：

```yaml
exit:
  mode: partial_take_profit_with_trailing
  partial_take_profit:
    enabled: true
    levels:
      - r: 2.0
        percent: 30
      - r: 4.0
        percent: 30
    runner_percent: 40
  trailing_stop:
    enabled: true
    method: swing
```

### PositionManager

- `core/execution/position_manager.py`

职责：

- 读取本地 open active position
- 查询 Binance 合约持仓
- 交易所仓位归零时标记本地仓位 `closed`
- 根据交易所仓位更新 `remaining_amount`
- EMA 跟随或结构离场触发 `reduceOnly` 市价平仓
- EMA 跟随使用 `exit.trailing_stop.ema.timeframe` 读取 K 线，默认 15m
- 结构离场使用 `exit.trailing_stop.structure.timeframe` 读取 K 线，默认 5m
- R 倍数移动止损触发撤换旧 STOP_MARKET，再创建新的 STOP_MARKET
- 有 active position 时阻止本轮扫描新入场

移动止损更新单：

```text
STOP_MARKET
reduceOnly=true
workingType=MARK_PRICE
```

## 12. 数据库

入口：

- `core/storage/database.py`

SQLite 表：

- signals
- orders
- active_positions
- trades
- trade_journal
- trade_events
- risk_events
- bot_state

### active_positions

用于记录当前正在管理的单个仓位：

- `status`: open / closing / closed
- `symbol`: 交易对
- `market_type`: 当前固定 futures
- `direction`: long / short
- `amount`: 初始成交数量
- `remaining_amount`: 交易所当前剩余数量
- `entry_price`: 入场价
- `stop_loss`: 初始止损
- `current_stop`: 当前保护止损
- `entry_order_id`: 入场单 ID
- `stop_order_id`: 当前 STOP_MARKET 单 ID
- `exit_plan`: 分批止盈和移动止损计划
- `partial_state`: 分批止盈订单和状态
- `raw`: 原始执行数据

### trade_journal

用于 AI 复盘的一笔交易摘要：

- 策略 ID / 名称 / 大类 / 方向模式
- 开仓和平仓时间
- 入场价、平仓价、初始止损、最终止损
- 仓位数量和剩余数量
- 估算 PnL、R 倍数、盈亏结果
- 离场原因
- 入场检查清单
- exit_plan
- partial_state
- market_context
- raw orders
- ai_review_notes

### trade_events

用于记录交易生命周期事件：

- `entry_submitted`
- `entry_filled`
- `protective_stop_placed`
- `partial_take_profit_placed`
- `position_size_changed`
- `trailing_stop_updated`
- `trade_closed`

第一版使用交易所持仓归零和本地离场动作生成复盘摘要；手续费、逐笔成交均价、分批止盈成交细节后续继续增强。

## 13. 复盘导出与清理

项目内 Codex skill：

- `.codex/skills/trade-review/SKILL.md`

导出脚本：

- `.codex/skills/trade-review/scripts/export_trade_review.py`

导出内容：

- `data/exports/trade_review/trade_review_latest.jsonl`
- `data/exports/trade_review/trade_stats_latest.csv`
- `data/exports/trade_review/trade_review_report.md`

清理脚本：

- `scripts/cleanup_trading_data.py`

清理脚本默认 dry-run，只有传入 `--confirm` 才会删除；建议同时传入 `--backup`。

## 14. 状态机

主循环逻辑：

```text
有 active_position:
  进入 PositionManager
  查询交易所真实持仓
  更新 remaining_amount
  管理移动止损、EMA/结构离场
  不扫描新入场

无 active_position:
  扫描策略信号
  通过风控后开仓
  等待成交
  挂保护止损
  挂分批止盈
  写入 active_positions
```

注意：分批止盈单在开仓成交后由 OrderManager 立即挂出；PositionManager 后续主要通过交易所持仓查询同步剩余仓位。

## 15. UI

入口：

- `app.py`

主要页签：

- 信号
- 订单
- 持仓
- 风控事件
- 策略
- 交易配置
- 合约
- API检测
- 配置

## 16. 运行方式

```bash
cd /Users/geyuming/Hobby/python/binance_quantize
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false --server.headless true
```

单次机器人：

```bash
python bot_runner.py --once
```

循环机器人：

```bash
python bot_runner.py --interval 60
```

## 17. 安全约束

- `.env` 不提交。
- API Key 不显示明文。
- futures 默认小仓位、低杠杆。
- 保护止损 required 默认开启。
- API Key 不应开启提现权限。

## 18. 后续开发项

- 强平价缓冲检查
- 更完整的成交回填和 trades 统计
- 分批止盈订单逐笔成交状态回填
- 移动止损和分批止盈订单的完整冲突处理
- 回测模块
- 参数优化模块
- WebSocket 行情与订单推送
