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

## 3. 配置模型

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

## 4. 配置加载

入口：

- `core/utils/config.py`

流程：

1. 读取 `config.yaml`
2. 读取 `strategies.yaml`
3. 应用 active_strategy 参数
4. 如果存在 `data/runtime_strategy.yaml`，再应用临时参数

## 5. Binance 接入

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

## 6. 策略模块

### 指标

- `core/strategy/indicators.py`

### 支撑压力和结构

- `core/strategy/support_resistance.py`

负责 swing high / swing low、HH/HL、LL/LH、支撑压力、突破/跌破、第一次回踩和利润空间。

### 策略引擎

- `core/strategy/ema_structure.py`

负责多周期行情准备、做多/做空 checklist、按启用检查项计算 score、生成 signal、计算结构止损和 RR。

## 7. 风控模块

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

## 8. 执行模块

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

## 9. 数据库

入口：

- `core/storage/database.py`

SQLite 表：

- signals
- orders
- active_positions
- trades
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

## 10. 状态机

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

## 11. UI

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

## 12. 运行方式

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

## 13. 安全约束

- `.env` 不提交。
- API Key 不显示明文。
- futures 默认小仓位、低杠杆。
- 保护止损 required 默认开启。
- API Key 不应开启提现权限。

## 14. 后续开发项

- 强平价缓冲检查
- 更完整的成交回填和 trades 统计
- 分批止盈订单逐笔成交状态回填
- 移动止损和分批止盈订单的完整冲突处理
- 回测模块
- 参数优化模块
- WebSocket 行情与订单推送
