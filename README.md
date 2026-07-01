# Binance Quantize

本地运行的 Binance USD-M Futures 短线量化交易系统。当前版本只开放 U 本位合约自动交易，支持 Streamlit 界面、Binance 行情、结构突破策略、SQLite 记录、dry_run、受控 live 下单、保护止损、分批止盈和持仓退出管理。

详细文档：

- 功能文档：`docs/functional_spec.md`
- 技术文档：`docs/technical_design.md`
- 历史需求与设计：`docs/requirements_and_design.md`

## 安装

```bash
cd /Users/geyuming/Hobby/python/binance_quantize
python3.12 -m venv .venv
source .venv/bin/activate
pip install --prefer-binary -r requirements.txt
cp .env.example .env
```

## 配置 API

在 Binance API Management 创建 API Key。

建议权限：

- Enable Reading: 开启
- Enable Futures: 开启
- Enable Withdrawals: 不要开启
- IP 白名单: 强烈建议开启

`.env`：

```env
BINANCE_API_KEY=你的_api_key
BINANCE_API_SECRET=你的_api_secret
ENABLE_LIVE_TRADING=false
```

确认极小金额实盘前再改为：

```env
ENABLE_LIVE_TRADING=true
```

## 运行界面

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false --server.headless true
```

浏览器打开：

```text
http://127.0.0.1:8501
```

## 单次运行

```bash
python bot_runner.py --once
```

## 循环运行

```bash
python bot_runner.py --interval 60
```

循环运行时，机器人会先检查是否存在本地 active position：

- 有持仓：只执行退出管理，不扫描新入场。
- 无持仓：扫描信号，通过风控后才尝试开仓。

## 合约默认配置

当前版本固定面向 U 本位合约：

```yaml
exchange:
  market_type: futures

futures:
  enabled: true
  allow_short: false
  leverage: 1
  max_leverage: 1
  margin_mode: isolated
  max_notional_usdt: 50
```

建议先保持：

```text
1x
逐仓
小仓位
dry_run
保护止损 required=true
```

## 策略配置

策略参数保存在 `strategies.yaml`。当前内置合约策略：

- 趋势突破类
  - `AI推荐-合约结构突破回踩`
  - `AI推荐-合约稳健`
  - `AI推荐-合约标准`
- 趋势回调类
  - `AI推荐-下跌趋势反弹空`
  - `AI推荐-上升趋势回调多`
- 日内波动回归类
  - `AI推荐-VWAP/ATR 日内回归多`
  - `AI推荐-VWAP/ATR 日内回归空`

策略页支持：

- 查看内置策略
- 一键使用
- 复制策略
- 临时应用本次参数
- 另存为自定义策略

可配置内容：

- 策略大类和方向模式
- 做多/做空入场检查项开关
- 多周期 EMA、结构、突破回踩、回调、VWAP/ATR 回归参数
- 移动止损
- 移动止损方法：R 倍数、EMA、前低/前高、结构位
- 分批止盈

## 保护止损

`交易配置` 页提供保护止损参数：

- 开仓后立即挂止损单
- 止损单失败则中止
- 等待成交秒数
- 超时未成交撤单
- 合约保护单类型

合约保护止损使用：

```text
STOP_MARKET
reduceOnly=true
workingType=MARK_PRICE
```

当前执行流程：

1. 提交入场单。
2. 等待入场成交，超时未成交可自动撤单。
3. 成交后立即挂 `STOP_MARKET` 保护止损。
4. 按退出计划挂分批止盈 `reduceOnly` 限价单。
5. 写入 `active_positions`，后续循环优先管理该仓位。

移动止损中的 R 倍数模式会撤换旧止损单并重新挂更优的 `STOP_MARKET`；EMA 跟随和结构离场会触发 `reduceOnly` 市价平仓。

## 配置代理

在 `config.yaml` 中：

```yaml
exchange:
  proxy:
    enabled: true
    url: http://127.0.0.1:7897
```

检查网络：

```bash
.venv/bin/python check_network.py
```

检查 API：

```bash
.venv/bin/python check_auth.py
```

## 交易复盘导出

SQLite 数据库保存在：

```text
data/trader.sqlite
```

导出给 Codex CLI / AI 分析的 JSONL、CSV 和 Markdown：

```bash
.venv/bin/python .codex/skills/trade-review/scripts/export_trade_review.py --limit 100
```

输出目录：

```text
data/exports/trade_review/
```

## 清理历史数据

先预览，不删除：

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90
```

确认删除前建议备份：

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90 --backup --confirm
```

清空所有交易运行数据需要显式确认：

```bash
.venv/bin/python scripts/cleanup_trading_data.py --all --backup --confirm
```
