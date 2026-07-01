# Binance Quantize 需求与开发文档

## 1. 当前产品目标

开发一个在本地 Mac 上运行的 Binance USD-M Futures 短线量化交易系统。

当前版本只开放 U 本位合约自动交易，现货入口已从产品配置和界面关闭。保留少量现货代码仅用于未来可能复用，不作为当前可用能力。

核心目标：

- 使用 Binance API 获取合约行情、账户和持仓数据。
- 使用多周期 EMA、市场结构、支撑压力、突破回踩、成交量和盈亏比生成交易信号。
- 支持 Streamlit 本地 Web 界面查看信号、订单、持仓、风控事件、策略和交易配置。
- 支持 dry_run 和受控 live。
- live 开仓成交后必须立即挂保护止损。
- 支持分批止盈和移动止损。
- 同一时间只管理一个 active position。
- 使用 SQLite 记录信号、订单、当前持仓、交易和风控事件。
- 使用 trade_journal 和 trade_events 保存交易生命周期，支持后续 AI 复盘。

## 2. 运行边界

当前固定市场：

```yaml
exchange:
  market_type: futures

futures:
  enabled: true
```

默认安全配置：

- 1x 杠杆
- 逐仓
- 小名义仓位
- 默认不允许做空
- 保护止损 required
- 平仓单必须 reduceOnly
- 不允许提现权限

## 3. Binance API 限制

Binance API 按请求权重和订单次数限制，不是简单按请求次数计算。

官方文档：

- USD-M Futures General Info: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- Spot Request Security: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/request-security

开发要求：

- 启动时尽量读取交易所 `exchangeInfo`。
- 观察响应头中的 `used_weight`。
- 接近限制时降低 REST 查询频率。
- 收到 429 时按 `Retry-After` 等待。
- 收到 418 时停止请求并报警。
- 循环间隔不应设置过低，开发期建议 30 到 60 秒以上。

常见默认限制以官方实时返回为准，USD-M Futures 常见 REQUEST_WEIGHT 为分钟级权重限制。

## 4. API 授权

用户在 Binance API Management 创建 API Key。

权限建议：

- Enable Reading: 开启
- Enable Futures: 开启
- Enable Withdrawals: 绝对不要开启
- Restrict access to trusted IPs only: 强烈建议开启

本地配置：

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
ENABLE_LIVE_TRADING=false
```

密钥只保存在本地 `.env`，程序不得写入日志、数据库或界面明文。界面只允许展示脱敏后的 key。

## 5. 策略需求

策略体系：

- 趋势突破类：突破关键结构后顺势跟随。
- 趋势回调类：大趋势明确时等待回调/反弹到关键位置后顺势入场。
- 日内波动回归类：日内振幅大但实体较小时，等待价格偏离 VWAP / 布林带后回归。

多周期默认：

- 趋势突破类：1h 判断大方向，15m 判断趋势启动，5m 判断入场。
- 趋势回调类：4h 判断大趋势，1h 判断回调/反弹位置，5m 判断入场。
- 日内波动回归类：1h 观察环境，15m 判断 VWAP/ATR/布林带偏离，5m 判断入场。

趋势突破类做多检查项：

做多检查项：

- 1小时：价格在 EMA200 上方
- 1小时：EMA21 向上
- 1小时：HH/HL 上涨结构
- 1小时：距离下一压力有足够利润空间
- 15分钟：EMA9 站上 EMA21
- 15分钟：EMA21 向上
- 15分钟：成交量放大
- 5分钟：突破关键压力
- 5分钟：第一次回踩不破
- 综合：盈亏比满足要求

趋势突破类做空检查项：

- 1小时：价格在 EMA200 下方
- 1小时：EMA21 向下
- 1小时：LL/LH 下跌结构
- 1小时：距离下一支撑有足够利润空间
- 15分钟：EMA9 跌破 EMA21
- 15分钟：EMA21 向下
- 15分钟：成交量放大
- 5分钟：跌破关键支撑
- 5分钟：反弹不过，支撑变压力
- 综合：盈亏比满足要求

策略配置要求：

- 内置策略不可直接修改。
- 可复制内置策略为自定义策略。
- 可临时应用本次参数，不保存到策略库。
- 可另存为自定义策略。
- 入场检查项用中文开关展示。
- 退出模式用中文展示。

当前内置策略：

- 趋势突破类：AI推荐-合约结构突破回踩、AI推荐-合约稳健、AI推荐-合约标准
- 趋势回调类：AI推荐-下跌趋势反弹空、AI推荐-上升趋势回调多
- 日内波动回归类：AI推荐-VWAP/ATR 日内回归多、AI推荐-VWAP/ATR 日内回归空

后续方向：

- 新增策略自动选择器。
- 根据趋势强弱、ATR、VWAP 偏离、布林带位置和区间结构，推荐当前更适合的策略大类。
- 第一阶段只做推荐，不自动切换；实盘稳定后再考虑自动切换。

## 6. 风控需求

硬性风控：

- 必须有止损价。
- 盈亏比必须达到配置阈值。
- 单笔风险按账户权益百分比计算。
- 单笔名义仓位不得超过配置上限。
- 同时最多一个 active position。
- futures.enabled 必须为 true。
- 做空必须显式开启 allow_short。
- 杠杆不得超过 max_leverage。
- API、行情或保护止损异常时记录风控事件。

仓位计算：

```text
risk_budget = equity * risk_per_trade_pct
amount = risk_budget / abs(entry - stop)
amount <= max_position_usdt / entry
```

## 7. 开仓和保护止损需求

live 开仓流程：

1. 风控通过后提交入场单。
2. 如果是限价单，等待成交。
3. 超时未成交时撤销入场单。
4. 成交后按实际成交数量挂保护止损。
5. 保护止损失败时记录 critical 风控事件。
6. 如果 required=true，保护止损失败会中止执行。
7. 挂分批止盈 reduceOnly 限价单。
8. 写入 active_positions。

合约保护止损：

```text
STOP_MARKET
reduceOnly=true
workingType=MARK_PRICE
```

## 8. 退出需求

退出模式分两层：

- 分批止盈 + 移动止损
- 移动止损

分批止盈：

- 根据初始风险 R 计算目标价。
- 在 +2R、+4R 等位置挂 reduceOnly 限价单。
- runner 仓位交给移动止损或趋势离场处理。

移动止损：

- R 倍数移动：达到指定 R 后撤换保护止损。
- EMA 跟随：价格破指定周期 EMA 后 reduceOnly 市价平仓，默认 15m EMA21，可在策略页手动切换。
- 前低/前高跟随：结构破坏后 reduceOnly 市价平仓。
- 结构位跟随：跌破或突破关键结构位后 reduceOnly 市价平仓。

## 9. 持仓状态机

主循环必须先处理已有仓位：

```text
有 active position:
  查询 Binance 合约持仓
  仓位归零则标记 closed
  仓位存在则更新 remaining_amount
  检查 EMA/结构离场
  检查 R 倍数移动止损
  不扫描新入场

没有 active position:
  扫描策略信号
  通过风控后开仓
  成交后挂保护止损
  挂分批止盈
  写入 active_positions
```

## 10. 技术栈

- Python 3.12
- Streamlit
- ccxt
- pandas / numpy
- plotly
- SQLite
- PyYAML
- python-dotenv
- loguru

## 11. 验收标准

- 本地 Streamlit 页面可以打开。
- 能读取 `config.yaml`、`strategies.yaml` 和 `.env`。
- 能初始化 SQLite。
- 能获取 Binance USD-M Futures K 线。
- 能展示 K 线、EMA、信号、订单、持仓和风控事件。
- 能生成多空策略信号。
- 能计算仓位、止损、止盈和盈亏比。
- dry_run 下不会真实下单。
- live 模式需要 `.env` 显式开启 `ENABLE_LIVE_TRADING=true`。
- live 开仓成交后立即挂保护止损。
- 能挂分批止盈 reduceOnly 限价单。
- 有 active position 时不扫描新入场。
- R 倍数移动止损能撤换 STOP_MARKET。
- EMA/结构离场能触发 reduceOnly 市价平仓。

## 12. 当前待增强项

- 强平价缓冲检查需要进一步接入真实持仓数据。
- 分批止盈订单成交后的逐笔状态回填需要增强。
- `trade_journal` 的手续费、精确成交均价、逐笔成交 PnL 需要补齐。
- 后续增加 AI 复盘总结字段自动生成。
- 后续可扩展 `trade-review` skill，让它自动生成策略调整建议和参数实验计划。
- WebSocket 行情与订单推送尚未实现。
- 回测和参数优化尚未实现。
