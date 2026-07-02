from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from copy import deepcopy

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from core.exchange.auth_check import signed_account_check
from core.exchange.client import BinanceClient
from core.storage.database import Database
from core.strategy.ema_structure import EmaStructureStrategy
from core.strategy.indicators import add_emas, ohlcv_to_df
from core.utils.config import (
    PROJECT_ROOT,
    clear_runtime_strategy,
    load_config,
    load_strategy_store,
    save_config,
    save_runtime_strategy,
    save_strategy_store,
)


st.set_page_config(page_title="Binance Quantize", layout="wide")


@st.cache_resource
def get_db() -> Database:
    db = Database()
    db.init()
    return db


def rows_to_df(rows: list) -> pd.DataFrame:
    return pd.DataFrame([dict(row) for row in rows])


def checks_to_df(checks: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [{"检查项": CHECK_LABELS.get(key, key), "满足": "✅" if bool(value) else "□"} for key, value in checks.items()]
    )


def refresh_signals_for_current_strategy(config: dict, db: Database) -> int:
    client = BinanceClient(config)
    strategy = EmaStructureStrategy(config)
    timeframes = config["strategy"]["timeframes"]
    inserted = 0
    for symbol in config.get("symbols", []):
        trend = client.fetch_ohlcv(symbol, timeframes["trend"], limit=260)
        confirm = client.fetch_ohlcv(symbol, timeframes["confirm"], limit=260)
        entry = client.fetch_ohlcv(symbol, timeframes["entry"], limit=260)
        signal = strategy.analyze(symbol, config["exchange"]["market_type"], trend, confirm, entry).to_record()
        # 手动刷新只用于查看当前策略检查项，不能走风控和下单流程。
        signal["details"]["manual_preview"] = True
        signal["details"]["strategy_snapshot"] = EmaStructureStrategy.strategy_snapshot(config)
        db.insert_signal(signal)
        inserted += 1
    return inserted


def render_signal_checklist(df: pd.DataFrame) -> None:
    if df.empty or "details" not in df.columns:
        return
    selected_id = st.selectbox("查看信号检查清单", df["id"].tolist(), index=0)
    row = df[df["id"] == selected_id].iloc[0]
    details = json.loads(row["details"]) if isinstance(row["details"], str) else row["details"]
    direction = row.get("direction", "none")
    snapshot = details.get("strategy_snapshot", {})
    if snapshot:
        st.caption(
            "信号生成策略："
            f"{snapshot.get('name') or snapshot.get('id') or '未知'} / "
            f"{FAMILY_LABELS.get(snapshot.get('family'), snapshot.get('family'))} / "
            f"{DIRECTION_MODE_LABELS.get(snapshot.get('direction_mode'), snapshot.get('direction_mode'))} / "
            f"周期 {snapshot.get('timeframes')}"
        )
    if details.get("manual_preview"):
        st.info("这条信号是手动刷新生成的策略检查预览，只写入信号记录，不会触发风控和下单。")
    st.caption(f"当前信号方向：{direction}")

    if direction == "long":
        st.markdown("**做多检查清单**")
        st.dataframe(checks_to_df(details.get("active_long_checks") or details.get("long_checks", {})), use_container_width=True, hide_index=True)
    elif direction == "short":
        st.markdown("**做空检查清单**")
        st.dataframe(checks_to_df(details.get("active_short_checks") or details.get("short_checks", {})), use_container_width=True, hide_index=True)
    else:
        st.warning("当前没有触发入场方向。下面展示的是做多/做空候选检查清单，不代表系统准备开多。")
        long_col, short_col = st.columns(2)
        with long_col:
            st.markdown("**做多候选检查**")
            st.dataframe(checks_to_df(details.get("active_long_checks") or details.get("long_checks", {})), use_container_width=True, hide_index=True)
        with short_col:
            st.markdown("**做空候选检查**")
            st.dataframe(checks_to_df(details.get("active_short_checks") or details.get("short_checks", {})), use_container_width=True, hide_index=True)
    st.json(
        {
            "structure": details.get("structure"),
            "trend_support": details.get("trend_support"),
            "trend_resistance": details.get("trend_resistance"),
            "entry_support": details.get("entry_support"),
            "entry_resistance": details.get("entry_resistance"),
            "long_rr_candidate": details.get("long_rr_candidate"),
            "short_rr_candidate": details.get("short_rr_candidate"),
        }
    )


def trading_status(config: dict) -> dict[str, str]:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    live_env = os.getenv("ENABLE_LIVE_TRADING", "").lower() == "true"
    trade_mode = config["exchange"]["trade_mode"]
    can_live_order = trade_mode == "live" and live_env and bool(api_key) and bool(api_secret)
    return {
        "api_key": "已配置" if api_key else "未配置",
        "api_secret": "已配置" if api_secret else "未配置",
        "live_env": "允许" if live_env else "禁止",
        "auto_order": "真实下单" if can_live_order else "不会真实下单",
    }


CHECK_LABELS = {
    "1h_price_above_ema200": "1小时：价格在 EMA200 上方",
    "1h_ema21_up": "1小时：EMA21 向上",
    "1h_hh_hl_structure": "1小时：HH/HL 上涨结构",
    "1h_profit_space_to_resistance": "1小时：到下一压力有足够利润空间",
    "15m_ema9_above_ema21": "15分钟：EMA9 站上 EMA21",
    "15m_ema21_up": "15分钟：EMA21 向上",
    "15m_volume_expanded": "15分钟：成交量放大",
    "5m_breakout_resistance": "5分钟：突破关键压力",
    "5m_first_pullback_holds": "5分钟：第一次回踩不破",
    "combined_stop_less_than_half_target": "综合：盈亏比满足要求",
    "1h_price_below_ema200": "1小时：价格在 EMA200 下方",
    "1h_ema21_down": "1小时：EMA21 向下",
    "1h_ll_lh_structure": "1小时：LL/LH 下跌结构",
    "1h_profit_space_to_support": "1小时：到下一支撑有足够利润空间",
    "15m_ema9_below_ema21": "15分钟：EMA9 跌破 EMA21",
    "15m_ema21_down": "15分钟：EMA21 向下",
    "5m_breakdown_support": "5分钟：跌破关键支撑",
    "5m_pullback_rejects_support_as_resistance": "5分钟：反弹不过，支撑变压力",
    "pullback_long_trend_up": "大周期：上升趋势成立",
    "pullback_long_near_support_or_ema": "回调：接近支撑/均线/VWAP",
    "pullback_long_entry_reclaims_ema9": "入场：重新站上 EMA9",
    "pullback_long_confirm_ema21_not_down": "确认：EMA21 未转弱",
    "pullback_long_rr_ok": "综合：回调多盈亏比满足",
    "pullback_short_trend_down": "大周期：下跌趋势成立",
    "pullback_short_near_resistance_or_ema": "反弹：接近压力/均线/VWAP",
    "pullback_short_entry_loses_ema9": "入场：跌回 EMA9 下方",
    "pullback_short_confirm_ema21_not_up": "确认：EMA21 未转强",
    "pullback_short_rr_ok": "综合：反弹空盈亏比满足",
    "reversion_long_volatility_enough": "日内：波动率足够",
    "reversion_long_below_vwap": "位置：价格明显低于 VWAP",
    "reversion_long_near_lower_band": "位置：接近布林下轨",
    "reversion_long_entry_reversal": "入场：5分钟止跌转强",
    "reversion_long_target_to_vwap_ok": "目标：回到 VWAP 盈亏比满足",
    "reversion_short_volatility_enough": "日内：波动率足够",
    "reversion_short_above_vwap": "位置：价格明显高于 VWAP",
    "reversion_short_near_upper_band": "位置：接近布林上轨",
    "reversion_short_entry_reversal": "入场：5分钟冲高转弱",
    "reversion_short_target_to_vwap_ok": "目标：回到 VWAP 盈亏比满足",
}

FAMILY_LABELS = {
    "trend_breakout": "趋势突破类",
    "trend_pullback": "趋势回调类",
    "intraday_mean_reversion": "日内波动回归类",
}

DIRECTION_MODE_LABELS = {
    "both": "多空双向",
    "long_only": "只做多",
    "short_only": "只做空",
}

EXIT_MODE_LABELS = {
    "partial_take_profit_with_trailing": "分批止盈 + 移动止损",
    "trailing_stop": "移动止损",
}

TRAILING_METHOD_LABELS = {
    "r_multiple": "按 R 倍数移动",
    "ema": "跟随 EMA",
    "swing": "跟随前低/前高",
    "structure": "跟随结构位",
}


def render_chart(config: dict) -> None:
    symbol = st.session_state.get("chart_symbol", config["symbols"][0])
    timeframe = st.session_state.get("chart_timeframe", config["strategy"]["timeframes"]["entry"])
    try:
        with st.spinner(f"正在加载 {symbol} {timeframe} 行情..."):
            client = BinanceClient(config)
            rows = client.fetch_ohlcv(symbol, timeframe, limit=220)
        strategy = config["strategy"]
        ema_periods = (int(strategy["ema_fast"]), int(strategy["ema_mid"]), int(strategy["ema_slow"]))
        df = add_emas(ohlcv_to_df(rows), ema_periods)
    except Exception as exc:
        st.warning(f"行情加载失败：{exc}")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df["datetime"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
        )
    )
    for period in ema_periods:
        fig.add_trace(go.Scatter(x=df["datetime"], y=df[f"ema{period}"], mode="lines", name=f"EMA{period}"))
    fig.update_layout(height=560, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)


def start_bot(interval: int) -> None:
    cmd = [sys.executable, str(PROJECT_ROOT / "bot_runner.py"), "--interval", str(interval)]
    subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))


def strategy_label(strategy: dict) -> str:
    suffix = "内置" if strategy.get("builtin") else "自定义"
    return f"{strategy['name']} ({suffix})"


def find_strategy(store: dict, strategy_id: str) -> dict | None:
    for strategy in store.get("strategies", []):
        if strategy.get("id") == strategy_id:
            return strategy
    return None


def copy_strategy(store: dict, source_id: str) -> str:
    source = find_strategy(store, source_id)
    if not source:
        raise ValueError("未找到策略")
    copied = deepcopy(source)
    new_id = f"custom_{int(time.time())}"
    copied["id"] = new_id
    copied["name"] = f"{source['name']} 副本"
    copied["builtin"] = False
    copied["editable"] = True
    copied["description"] = "从内置策略复制，可自由调整。"
    store.setdefault("strategies", []).append(copied)
    save_strategy_store(store)
    return new_id


def save_strategy_copy(store: dict, source: dict, name: str, description: str, params: dict) -> str:
    copied = deepcopy(source)
    new_id = f"custom_{int(time.time())}"
    copied["id"] = new_id
    copied["name"] = name
    copied["description"] = description
    copied["builtin"] = False
    copied["editable"] = True
    copied["params"] = params
    store.setdefault("strategies", []).append(copied)
    store["active_strategy"] = new_id
    save_strategy_store(store)
    clear_runtime_strategy()
    return new_id


def use_strategy(store: dict, strategy_id: str) -> None:
    if not find_strategy(store, strategy_id):
        raise ValueError("未找到策略")
    store["active_strategy"] = strategy_id
    save_strategy_store(store)
    clear_runtime_strategy()


def build_default_check_map(keys: list[str], source: dict | None = None) -> dict[str, bool]:
    source = source or {}
    return {key: bool(source.get(key, True)) for key in keys}


def check_keys_for_family(family: str) -> tuple[list[str], list[str]]:
    if family == "trend_pullback":
        return (
            [
                "pullback_long_trend_up",
                "pullback_long_near_support_or_ema",
                "pullback_long_entry_reclaims_ema9",
                "pullback_long_confirm_ema21_not_down",
                "pullback_long_rr_ok",
            ],
            [
                "pullback_short_trend_down",
                "pullback_short_near_resistance_or_ema",
                "pullback_short_entry_loses_ema9",
                "pullback_short_confirm_ema21_not_up",
                "pullback_short_rr_ok",
            ],
        )
    if family == "intraday_mean_reversion":
        return (
            [
                "reversion_long_volatility_enough",
                "reversion_long_below_vwap",
                "reversion_long_near_lower_band",
                "reversion_long_entry_reversal",
                "reversion_long_target_to_vwap_ok",
            ],
            [
                "reversion_short_volatility_enough",
                "reversion_short_above_vwap",
                "reversion_short_near_upper_band",
                "reversion_short_entry_reversal",
                "reversion_short_target_to_vwap_ok",
            ],
        )
    return (
        [
            "1h_price_above_ema200",
            "1h_ema21_up",
            "1h_hh_hl_structure",
            "1h_profit_space_to_resistance",
            "15m_ema9_above_ema21",
            "15m_ema21_up",
            "15m_volume_expanded",
            "5m_breakout_resistance",
            "5m_first_pullback_holds",
            "combined_stop_less_than_half_target",
        ],
        [
            "1h_price_below_ema200",
            "1h_ema21_down",
            "1h_ll_lh_structure",
            "1h_profit_space_to_support",
            "15m_ema9_below_ema21",
            "15m_ema21_down",
            "15m_volume_expanded",
            "5m_breakdown_support",
            "5m_pullback_rejects_support_as_resistance",
            "combined_stop_less_than_half_target",
        ],
    )


def render_strategy_tree_selector(strategies: list[dict], active_id: str) -> str:
    # 树状选择直接按“大类 -> 策略”组织，避免平铺列表让一级分类失去意义。
    family_options = ["trend_breakout", "trend_pullback", "intraday_mean_reversion"]
    strategy_ids = [item["id"] for item in strategies]
    if "strategy_selector_id" not in st.session_state or st.session_state["strategy_selector_id"] not in strategy_ids:
        st.session_state["strategy_selector_id"] = active_id if active_id in strategy_ids else strategy_ids[0]

    selected_id = st.session_state["strategy_selector_id"]
    selected_family = (find_strategy({"strategies": strategies}, selected_id) or {}).get("params", {}).get("strategy", {}).get("family")
    st.markdown("**策略树**")
    for family in family_options:
        family_items = [item for item in strategies if item.get("params", {}).get("strategy", {}).get("family", "trend_breakout") == family]
        if not family_items:
            continue
        expanded = family == selected_family
        with st.expander(FAMILY_LABELS.get(family, family), expanded=expanded):
            for item in family_items:
                marker = "当前使用" if item["id"] == active_id else ("正在查看" if item["id"] == selected_id else "")
                label = f"{item['name']}（{'内置' if item.get('builtin') else '自定义'}）"
                if marker:
                    label = f"{label} - {marker}"
                if st.button(label, key=f"select_strategy_{item['id']}", use_container_width=True):
                    st.session_state["strategy_selector_id"] = item["id"]
                    st.rerun()
    return st.session_state["strategy_selector_id"]


def render_strategy_editor(store: dict) -> None:
    strategies = store.get("strategies", [])
    if not strategies:
        st.warning("未找到策略配置。")
        return

    active_id = store.get("active_strategy", "")
    family_options = ["trend_breakout", "trend_pullback", "intraday_mean_reversion"]
    selected_id = render_strategy_tree_selector(strategies, active_id)
    selected = find_strategy(store, selected_id)
    if not selected:
        st.warning("未找到所选策略，请重新选择。")
        return
    selected_id = selected["id"]
    params = selected["params"]
    strategy_params = params["strategy"]
    execution_params = params["execution"]
    editable = bool(selected.get("editable", False)) and not bool(selected.get("builtin", False))
    family = strategy_params.get("family", "trend_breakout")
    direction_mode = strategy_params.get("direction_mode", "both")
    long_check_keys, short_check_keys = check_keys_for_family(family)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前使用", "是" if selected_id == active_id else "否")
    c2.metric("类型", "内置" if selected.get("builtin") else "自定义")
    c3.metric("可编辑", "是" if editable else "否")
    c4.metric("大类", FAMILY_LABELS.get(family, family))
    st.caption(selected.get("description", ""))

    action_col1, action_col2, action_col3 = st.columns([1, 1, 2])
    if action_col1.button("一键使用", use_container_width=True, key=f"use_{selected_id}"):
        with st.spinner("正在切换当前策略..."):
            use_strategy(store, selected_id)
        st.success("已设为当前策略。")
        st.rerun()
    if action_col2.button("复制策略", use_container_width=True, key=f"copy_{selected_id}"):
        with st.spinner("正在复制策略并切换使用..."):
            new_id = copy_strategy(store, selected_id)
            use_strategy(load_strategy_store(), new_id)
        st.success("已复制并设为当前策略。")
        st.rerun()

    if not editable:
        st.info("内置策略不可直接保存。你可以临时应用本次参数，或另存为自定义策略。")

    with st.form(f"strategy_form_{selected_id}"):
        st.subheader("基础信息")
        new_name = st.text_input("策略名称", value=selected["name"])
        new_desc = st.text_area("说明", value=selected.get("description", ""), height=80)

        st.subheader("周期")
        tf1, tf2, tf3 = st.columns(3)
        trend_tf = tf1.selectbox("趋势周期", ["30m", "1h", "2h", "4h"], index=["30m", "1h", "2h", "4h"].index(strategy_params["timeframes"]["trend"]))
        confirm_tf = tf2.selectbox("确认周期", ["5m", "15m", "30m", "1h"], index=["5m", "15m", "30m", "1h"].index(strategy_params["timeframes"]["confirm"]))
        entry_tf = tf3.selectbox("入场周期", ["1m", "3m", "5m", "15m"], index=["1m", "3m", "5m", "15m"].index(strategy_params["timeframes"]["entry"]))

        st.subheader("策略分类")
        f1, f2 = st.columns(2)
        family_label = f1.selectbox(
            "策略大类",
            [FAMILY_LABELS[item] for item in family_options],
            index=family_options.index(family if family in family_options else "trend_breakout"),
        )
        family = family_options[[FAMILY_LABELS[item] for item in family_options].index(family_label)]
        direction_options = ["both", "long_only", "short_only"]
        direction_label = f2.selectbox(
            "方向模式",
            [DIRECTION_MODE_LABELS[item] for item in direction_options],
            index=direction_options.index(direction_mode if direction_mode in direction_options else "both"),
        )
        direction_mode = direction_options[[DIRECTION_MODE_LABELS[item] for item in direction_options].index(direction_label)]

        st.subheader("指标参数")
        p1, p2, p3 = st.columns(3)
        ema_fast = p1.number_input("EMA 快线", min_value=3, max_value=50, value=int(strategy_params["ema_fast"]), step=1)
        ema_mid = p2.number_input("EMA 中线", min_value=5, max_value=100, value=int(strategy_params["ema_mid"]), step=1)
        ema_slow = p3.number_input("EMA 慢线", min_value=50, max_value=400, value=int(strategy_params["ema_slow"]), step=5)

        p4, p5, p6 = st.columns(3)
        min_rr = p4.number_input("最小盈亏比", min_value=1.0, max_value=5.0, value=float(strategy_params["min_rr"]), step=0.1)
        volume_window = p5.number_input("成交量均值窗口", min_value=5, max_value=100, value=int(strategy_params["volume_window"]), step=1)
        volume_multiplier = p6.number_input("放量倍数", min_value=1.0, max_value=5.0, value=float(strategy_params["volume_multiplier"]), step=0.05)

        p7, p8, p9 = st.columns(3)
        structure_lookback = p7.number_input("结构回看根数", min_value=3, max_value=50, value=int(strategy_params["structure_lookback"]), step=1)
        stop_loss_pct = p8.number_input("止损百分比", min_value=0.1, max_value=10.0, value=float(execution_params["stop_loss_pct"]), step=0.1)
        take_profit_pct = p9.number_input("止盈百分比", min_value=0.1, max_value=20.0, value=float(execution_params["take_profit_pct"]), step=0.1)

        p10, p11, p12 = st.columns(3)
        swing_window = p10.number_input("摆动点窗口", min_value=1, max_value=10, value=int(strategy_params.get("swing_window", 2)), step=1)
        breakout_lookback = p11.number_input("突破回看根数", min_value=2, max_value=30, value=int(strategy_params.get("breakout_lookback", 6)), step=1)
        pullback_lookback = p12.number_input("回踩确认根数", min_value=2, max_value=30, value=int(strategy_params.get("pullback_lookback", 8)), step=1)

        p13, p14 = st.columns(2)
        level_tolerance_pct = p13.number_input("支撑压力容差 %", min_value=0.01, max_value=2.0, value=float(strategy_params.get("level_tolerance_pct", 0.15)), step=0.01)
        min_check_score = p14.number_input("最小打勾比例", min_value=0.5, max_value=1.0, value=float(strategy_params.get("min_check_score", 0.85)), step=0.01)

        if family == "intraday_mean_reversion":
            rv1, rv2 = st.columns(2)
            mean_reversion_min_vwap_deviation_pct = rv1.number_input(
                "VWAP 最小偏离 %",
                min_value=0.1,
                max_value=5.0,
                value=float(strategy_params.get("mean_reversion_min_vwap_deviation_pct", 0.6)),
                step=0.1,
            )
            mean_reversion_min_atr_pct = rv2.number_input(
                "ATR 最小波动 %",
                min_value=0.1,
                max_value=10.0,
                value=float(strategy_params.get("mean_reversion_min_atr_pct", 0.8)),
                step=0.1,
            )
        else:
            mean_reversion_min_vwap_deviation_pct = float(strategy_params.get("mean_reversion_min_vwap_deviation_pct", 0.6))
            mean_reversion_min_atr_pct = float(strategy_params.get("mean_reversion_min_atr_pct", 0.8))

        st.subheader("入场条件开关")
        lc1, lc2 = st.columns(2)
        long_enabled: dict[str, bool] = {}
        short_enabled: dict[str, bool] = {}
        default_long = build_default_check_map(long_check_keys, strategy_params.get("enabled_long_checks"))
        default_short = build_default_check_map(short_check_keys, strategy_params.get("enabled_short_checks"))
        with lc1:
            st.caption("做多")
            for key in long_check_keys:
                long_enabled[key] = st.checkbox(CHECK_LABELS.get(key, key), value=default_long[key], key=f"{selected_id}_long_{key}")
        with lc2:
            st.caption("做空")
            for key in short_check_keys:
                short_enabled[key] = st.checkbox(CHECK_LABELS.get(key, key), value=default_short[key], key=f"{selected_id}_short_{key}")

        exit_params = params.get("exit", {})
        trailing = exit_params.get("trailing_stop", {})
        partial = exit_params.get("partial_take_profit", {})

        st.subheader("止盈止损策略")
        exit_mode_options = ["partial_take_profit_with_trailing", "trailing_stop"]
        selected_exit_mode_label = st.selectbox(
            "退出模式",
            [EXIT_MODE_LABELS[item] for item in exit_mode_options],
            index=exit_mode_options.index(exit_params.get("mode", "partial_take_profit_with_trailing")),
        )
        exit_mode = exit_mode_options[[EXIT_MODE_LABELS[item] for item in exit_mode_options].index(selected_exit_mode_label)]
        st.success(f"当前生效退出模式：{EXIT_MODE_LABELS[exit_mode]}")

        partial_enabled = exit_mode == "partial_take_profit_with_trailing"
        if partial_enabled:
            st.markdown("**模块一：分批止盈**")
            st.info("分批止盈用于先锁定部分利润，剩余仓位交给移动止损继续持有。")
            default_levels = partial.get("levels", [{"r": 2.0, "percent": 30}, {"r": 4.0, "percent": 30}, {"r": 999, "percent": 40}])
            runner_percent_default = int(partial.get("runner_percent", default_levels[2].get("percent", 40) if len(default_levels) > 2 else 40))
            while len(default_levels) < 2:
                default_levels.append({"r": 4.0, "percent": 30})
            tp1, tp2, tp3, tp4, tp5 = st.columns(5)
            tp1_r = tp1.number_input("第1档 R", min_value=0.5, max_value=20.0, value=float(default_levels[0]["r"]), step=0.5)
            tp1_pct = tp2.number_input("第1档 %", min_value=0, max_value=100, value=int(default_levels[0]["percent"]), step=5)
            tp2_r = tp3.number_input("第2档 R", min_value=0.5, max_value=50.0, value=float(default_levels[1]["r"]), step=0.5)
            tp2_pct = tp4.number_input("第2档 %", min_value=0, max_value=100, value=int(default_levels[1]["percent"]), step=5)
            runner_pct = tp5.number_input("剩余奔跑 %", min_value=0, max_value=100, value=runner_percent_default, step=5)
            st.caption(f"生效：{tp1_r}R 平 {tp1_pct}%，{tp2_r}R 平 {tp2_pct}%，剩余 {runner_pct}% 使用移动止损。")
        else:
            st.info("当前只使用移动止损，不启用分批止盈。")
            tp1_r = float(partial.get("levels", [{"r": 2.0}])[0].get("r", 2.0))
            tp1_pct = int(partial.get("levels", [{"percent": 30}])[0].get("percent", 30))
            levels = partial.get("levels", [{"r": 2.0, "percent": 30}, {"r": 4.0, "percent": 30}])
            tp2_r = float(levels[1].get("r", 4.0)) if len(levels) > 1 else 4.0
            tp2_pct = int(levels[1].get("percent", 30)) if len(levels) > 1 else 30
            runner_pct = int(partial.get("runner_percent", 40))

        st.markdown("**模块二：移动止损 / 利润奔跑**")
        trailing_enabled = True
        trailing_method_options = ["r_multiple", "ema", "swing", "structure"]
        trailing_method = trailing.get("method", "swing")
        selected_trailing_label = st.selectbox(
            "移动止损方法",
            [TRAILING_METHOD_LABELS[item] for item in trailing_method_options],
            index=trailing_method_options.index(trailing_method if trailing_method in trailing_method_options else "swing"),
        )
        trailing_method = trailing_method_options[[TRAILING_METHOD_LABELS[item] for item in trailing_method_options].index(selected_trailing_label)]

        r_config = trailing.get("r_multiple", {})
        ema_config = trailing.get("ema", {})
        swing_config = trailing.get("swing", {})
        structure_config = trailing.get("structure", {})

        if trailing_method == "r_multiple":
            x1, x2 = st.columns(2)
            breakeven_at_r = x1.number_input("几 R 后移到保本", min_value=0.5, max_value=10.0, value=float(r_config.get("breakeven_at_r", 2.0)), step=0.5)
            trail_step_r = x2.number_input("移动止损步进 R", min_value=0.5, max_value=10.0, value=float(r_config.get("trail_step_r", 2.0)), step=0.5)
        else:
            breakeven_at_r = float(r_config.get("breakeven_at_r", 2.0))
            trail_step_r = float(r_config.get("trail_step_r", 2.0))

        if trailing_method == "ema":
            x3, x4 = st.columns(2)
            ema_follow_tf = x3.selectbox("EMA 跟随周期", ["5m", "15m", "30m", "1h"], index=["5m", "15m", "30m", "1h"].index(ema_config.get("timeframe", "15m")))
            ema_follow_period = x4.number_input("EMA 周期", min_value=9, max_value=200, value=int(ema_config.get("period", 21)), step=1)
        else:
            ema_follow_tf = ema_config.get("timeframe", "15m")
            ema_follow_period = int(ema_config.get("period", 21))

        if trailing_method == "swing":
            swing_window = st.number_input("前低/前高摆动窗口", min_value=1, max_value=10, value=int(swing_config.get("window", 2)), step=1)
        else:
            swing_window = int(swing_config.get("window", 2))

        if trailing_method == "structure":
            structure_tf = st.selectbox("结构位周期", ["5m", "15m", "30m", "1h"], index=["5m", "15m", "30m", "1h"].index(structure_config.get("timeframe", "5m")))
        else:
            structure_tf = structure_config.get("timeframe", "5m")

        if trailing_method == "r_multiple":
            st.caption(f"生效移动止损：盈利达到 {breakeven_at_r}R 后移到保本，之后每 {trail_step_r}R 阶梯上移。")
        elif trailing_method == "ema":
            st.caption(f"生效移动止损：价格跌破/突破 {ema_follow_tf} EMA{ema_follow_period} 时离场。")
        elif trailing_method == "swing":
            st.caption(f"生效移动止损：跟随最近前低/前高，摆动窗口 {swing_window}。")
        else:
            st.caption(f"生效移动止损：跟随 {structure_tf} 结构支撑/压力。")

        save_col1, save_col2 = st.columns(2)
        temp_submitted = save_col1.form_submit_button("临时应用本次参数", use_container_width=True)
        save_submitted = save_col2.form_submit_button("另存为策略并使用", type="primary", use_container_width=True)

    if temp_submitted or save_submitted:
        new_params = {
            "strategy": {
            "timeframes": {"trend": trend_tf, "confirm": confirm_tf, "entry": entry_tf},
            "family": family,
            "direction_mode": direction_mode,
            "ema_fast": int(ema_fast),
            "ema_mid": int(ema_mid),
            "ema_slow": int(ema_slow),
            "min_rr": float(min_rr),
            "volume_window": int(volume_window),
            "volume_multiplier": float(volume_multiplier),
            "structure_lookback": int(structure_lookback),
            "swing_window": int(swing_window),
            "breakout_lookback": int(breakout_lookback),
            "pullback_lookback": int(pullback_lookback),
            "level_tolerance_pct": float(level_tolerance_pct),
            "min_check_score": float(min_check_score),
            "mean_reversion_min_vwap_deviation_pct": float(mean_reversion_min_vwap_deviation_pct),
            "mean_reversion_min_atr_pct": float(mean_reversion_min_atr_pct),
            "enabled_long_checks": long_enabled,
            "enabled_short_checks": short_enabled,
            },
            "execution": {
                **execution_params,
                "stop_loss_pct": float(stop_loss_pct),
                "take_profit_pct": float(take_profit_pct),
            },
            "exit": {
                "mode": exit_mode,
                "partial_take_profit": {
                    "enabled": bool(partial_enabled),
                    "levels": [
                        {"r": float(tp1_r), "percent": int(tp1_pct)},
                        {"r": float(tp2_r), "percent": int(tp2_pct)},
                    ],
                    "runner_percent": int(runner_pct),
                },
                "trailing_stop": {
                    "enabled": bool(trailing_enabled),
                    "method": trailing_method,
                    "r_multiple": {
                        "breakeven_at_r": float(breakeven_at_r),
                        "trail_step_r": float(trail_step_r),
                    },
                    "ema": {
                        "timeframe": ema_follow_tf,
                        "period": int(ema_follow_period),
                    },
                    "swing": {
                        "window": int(swing_window),
                    },
                    "structure": {
                        "timeframe": structure_tf,
                    },
                },
            },
        }
        if temp_submitted:
            with st.spinner("正在临时应用本次策略参数..."):
                save_runtime_strategy(new_params)
            st.success("已临时应用。本次运行会使用这些参数；另存为策略前不会写入策略库。")
        else:
            with st.spinner("正在另存为自定义策略并切换使用..."):
                save_strategy_copy(store, selected, new_name, new_desc, new_params)
            st.success("已另存为自定义策略并设为当前使用。")
        st.rerun()


def render_trade_config(config: dict) -> None:
    st.subheader("交易配置")
    with st.form("trade_config_form"):
        e1, e2, e3 = st.columns(3)
        market_type = e1.selectbox("市场类型", ["futures"], index=0)
        trade_mode = e2.selectbox("交易模式", ["dry_run", "live"], index=["dry_run", "live"].index(config["exchange"]["trade_mode"]))
        proxy_enabled = e3.checkbox("启用代理", value=bool(config["exchange"].get("proxy", {}).get("enabled", False)))
        st.caption("当前版本只开放 Binance USD-M Futures U 本位合约自动交易。")
        proxy_url = st.text_input("代理地址", value=config["exchange"].get("proxy", {}).get("url", ""))

        symbols_text = st.text_area("交易币种，每行一个", value="\n".join(config.get("symbols", [])), height=80)

        r1, r2, r3 = st.columns(3)
        risk_per_trade_pct = r1.number_input("单笔风险 %", min_value=0.01, max_value=5.0, value=float(config["risk"]["risk_per_trade_pct"]), step=0.05)
        daily_loss_limit_pct = r2.number_input("日亏损上限 %", min_value=0.1, max_value=20.0, value=float(config["risk"]["daily_loss_limit_pct"]), step=0.1)
        max_position_usdt = r3.number_input("最大仓位 USDT", min_value=5.0, max_value=100000.0, value=float(config["risk"]["max_position_usdt"]), step=5.0)

        r4, r5, r6 = st.columns(3)
        max_consecutive_losses = r4.number_input("最大连续亏损", min_value=1, max_value=20, value=int(config["risk"]["max_consecutive_losses"]), step=1)
        max_open_positions = r5.number_input("最大同时持仓", min_value=1, max_value=20, value=int(config["risk"]["max_open_positions"]), step=1)
        require_stop_loss = r6.checkbox("必须有止损", value=bool(config["risk"]["require_stop_loss"]))

        st.subheader("保护止损")
        protective = config.get("execution", {}).get("protective_stop", {})
        ps1, ps2, ps3 = st.columns(3)
        protective_enabled = ps1.checkbox("开仓后立即挂止损单", value=bool(protective.get("enabled", True)))
        protective_required = ps2.checkbox("止损单失败则中止", value=bool(protective.get("required", True)))
        futures_type = ps3.selectbox("合约保护单类型", ["stop_market"], index=0)
        ps4, ps5 = st.columns(2)
        wait_entry_fill_seconds = ps4.number_input("等待成交秒数", min_value=1, max_value=300, value=int(protective.get("wait_entry_fill_seconds", 20)), step=1)
        cancel_unfilled_entry = ps5.checkbox("超时未成交撤单", value=bool(protective.get("cancel_unfilled_entry", True)))

        submitted = st.form_submit_button("保存交易配置", type="primary", use_container_width=True)

    if submitted:
        updated = deepcopy(config)
        updated["exchange"]["market_type"] = market_type
        updated["exchange"]["trade_mode"] = trade_mode
        updated["exchange"]["proxy"] = {"enabled": proxy_enabled, "url": proxy_url}
        updated["symbols"] = [line.strip() for line in symbols_text.splitlines() if line.strip()]
        updated["risk"].update(
            {
                "risk_per_trade_pct": float(risk_per_trade_pct),
                "daily_loss_limit_pct": float(daily_loss_limit_pct),
                "max_consecutive_losses": int(max_consecutive_losses),
                "max_open_positions": int(max_open_positions),
                "max_position_usdt": float(max_position_usdt),
                "require_stop_loss": bool(require_stop_loss),
            }
        )
        updated["execution"]["protective_stop"] = {
            "enabled": bool(protective_enabled),
            "required": bool(protective_required),
            "wait_entry_fill_seconds": int(wait_entry_fill_seconds),
            "cancel_unfilled_entry": bool(cancel_unfilled_entry),
            "futures_type": futures_type,
        }
        with st.spinner("正在保存交易配置..."):
            save_config(updated)
        st.success("交易配置已保存。")
        st.rerun()


def render_futures_config(config: dict) -> None:
    st.subheader("合约配置")
    futures = config.get("futures", {})
    st.info("合约功能默认受限。建议先使用 1x、逐仓、小名义金额，并确认 API Futures 权限已开启。")
    with st.form("futures_config_form"):
        f1, f2, f3 = st.columns(3)
        enabled = f1.checkbox("启用合约模块", value=bool(futures.get("enabled", False)))
        allow_short = f2.checkbox("允许做空", value=bool(futures.get("allow_short", False)))
        margin_mode = f3.selectbox("保证金模式", ["isolated", "cross"], index=["isolated", "cross"].index(futures.get("margin_mode", "isolated")))

        f4, f5, f6 = st.columns(3)
        leverage = f4.number_input("杠杆", min_value=1, max_value=20, value=int(futures.get("leverage", 1)), step=1)
        max_leverage = f5.number_input("最大允许杠杆", min_value=1, max_value=20, value=int(futures.get("max_leverage", 1)), step=1)
        max_notional_usdt = f6.number_input("最大名义仓位 USDT", min_value=5.0, max_value=100000.0, value=float(futures.get("max_notional_usdt", 50)), step=5.0)

        f7, f8, f9 = st.columns(3)
        require_reduce_only_close = f7.checkbox("平仓强制 reduceOnly", value=bool(futures.get("require_reduce_only_close", True)))
        require_protective_stop = f8.checkbox("要求保护止损", value=bool(futures.get("require_protective_stop", True)))
        min_liquidation_buffer_pct = f9.number_input("最小强平缓冲 %", min_value=1.0, max_value=50.0, value=float(futures.get("min_liquidation_buffer_pct", 5.0)), step=0.5)

        submitted = st.form_submit_button("保存合约配置", type="primary", use_container_width=True)

    if submitted:
        updated = deepcopy(config)
        updated["futures"] = {
            "enabled": bool(enabled),
            "allow_short": bool(allow_short),
            "leverage": int(leverage),
            "max_leverage": int(max_leverage),
            "margin_mode": margin_mode,
            "max_notional_usdt": float(max_notional_usdt),
            "require_reduce_only_close": bool(require_reduce_only_close),
            "require_protective_stop": bool(require_protective_stop),
            "min_liquidation_buffer_pct": float(min_liquidation_buffer_pct),
        }
        with st.spinner("正在保存合约配置..."):
            save_config(updated)
        st.success("合约配置已保存。")
        st.rerun()

    st.subheader("当前合约状态")
    cols = st.columns(4)
    cols[0].metric("市场类型", config["exchange"]["market_type"])
    cols[1].metric("合约模块", "开启" if futures.get("enabled") else "关闭")
    cols[2].metric("杠杆", futures.get("leverage", 1))
    cols[3].metric("允许做空", "是" if futures.get("allow_short") else "否")

    if config["exchange"]["market_type"] == "futures":
        if st.button("读取合约持仓", use_container_width=True):
            try:
                with st.spinner("正在从 Binance 读取合约持仓..."):
                    positions = BinanceClient(config).fetch_positions(config.get("symbols", []))
                rows = [
                    {
                        "symbol": item.get("symbol"),
                        "side": item.get("side"),
                        "contracts": item.get("contracts"),
                        "notional": item.get("notional"),
                        "entryPrice": item.get("entryPrice"),
                        "liquidationPrice": item.get("liquidationPrice"),
                        "unrealizedPnl": item.get("unrealizedPnl"),
                        "leverage": item.get("leverage"),
                        "marginMode": item.get("marginMode"),
                    }
                    for item in positions
                    if float(item.get("contracts") or 0) != 0
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"读取合约持仓失败：{exc}")


def main() -> None:
    config = load_config()
    strategy_store = load_strategy_store()
    db = get_db()

    st.title("Binance Quantize")
    status = db.get_state("bot_status", "paused")
    last_error = db.get_state("last_error", "")
    trade_status = trading_status(config)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("机器人状态", status)
    c2.metric("市场", config["exchange"]["market_type"])
    c3.metric("模式", config["exchange"]["trade_mode"])
    proxy = config["exchange"].get("proxy", {})
    c4.metric("代理", "开启" if proxy.get("enabled") else "关闭")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("API Key", trade_status["api_key"])
    c6.metric("API Secret", trade_status["api_secret"])
    c7.metric("实盘开关", trade_status["live_env"])
    c8.metric("自动下单", trade_status["auto_order"])

    active_strategy = config.get("active_strategy", {})
    st.caption(f"当前策略：{active_strategy.get('name', '未设置')}")

    if last_error:
        st.error(last_error)

    with st.sidebar:
        st.header("控制")
        if proxy.get("enabled"):
            st.caption(f"代理：{proxy.get('url')}")
        interval = st.number_input("循环间隔秒", min_value=30, max_value=3600, value=60, step=30)
        if st.button("启动机器人", type="primary", use_container_width=True):
            with st.spinner("正在启动机器人循环..."):
                db.set_state("bot_status", "running")
                start_bot(int(interval))
            st.success("已启动")
        if st.button("暂停机器人", use_container_width=True):
            with st.spinner("正在暂停机器人..."):
                db.set_state("bot_status", "paused")
            st.warning("已暂停")
        if st.button("紧急停止", use_container_width=True):
            with st.spinner("正在写入紧急停止状态..."):
                db.set_state("bot_status", "emergency_stop")
            st.error("已触发紧急停止")

        st.header("图表")
        st.session_state["chart_symbol"] = st.selectbox("币种", config["symbols"])
        st.session_state["chart_timeframe"] = st.selectbox("周期", ["5m", "15m", "1h"], index=0)

    render_chart(config)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs(
        ["信号", "订单", "持仓", "交易复盘", "交易事件", "风控事件", "策略", "交易配置", "合约", "API检测", "配置"]
    )
    with tab1:
        st.caption("信号检查项来自该条信号生成时的策略快照。切换策略后，需要机器人下一轮循环或点击下方按钮，才会生成当前策略的新检查项。")
        refresh_col1, refresh_col2 = st.columns([1, 3])
        if refresh_col1.button("按当前策略刷新信号", use_container_width=True):
            try:
                with st.spinner("正在按当前策略拉取行情并计算检查项，不会下单..."):
                    inserted = refresh_signals_for_current_strategy(config, db)
                st.success(f"已按当前策略刷新 {inserted} 条信号；本操作不会下单。")
                st.rerun()
            except Exception as exc:
                st.error(f"刷新信号失败：{exc}")
        refresh_col2.info(f"自动更新频率取决于机器人循环间隔；当前侧边栏默认间隔为 {int(interval)} 秒。有持仓时机器人只管理仓位，不扫描新入场信号。")
        df = rows_to_df(db.recent_rows("signals", 100))
        st.dataframe(df, use_container_width=True, hide_index=True)
        render_signal_checklist(df)
    with tab2:
        df = rows_to_df(db.recent_rows("orders", 100))
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab3:
        df = rows_to_df(db.recent_rows("active_positions", 50))
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab4:
        df = rows_to_df(db.recent_rows("trade_journal", 100))
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab5:
        df = rows_to_df(db.recent_rows("trade_events", 200))
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab6:
        df = rows_to_df(db.recent_rows("risk_events", 100))
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab7:
        render_strategy_editor(strategy_store)
    with tab8:
        render_trade_config(config)
    with tab9:
        render_futures_config(config)
    with tab10:
        st.subheader("API 认证检测")
        st.caption("只调用账户查询接口，不会下单。用于判断 Key、Secret、IP 白名单和权限是否有效。")
        if st.button("检测 API 认证", type="primary"):
            with st.spinner("正在调用 Binance 账户接口检测 API 认证..."):
                result = signed_account_check(config)
            if result.get("ok"):
                st.success("API 认证通过。")
            else:
                st.error("API 认证失败。")
            st.json(result)
    with tab11:
        st.code(json.dumps(config, ensure_ascii=False, indent=2), language="json")
        st.info(
            "真实下单需要同时满足：config.yaml 中 trade_mode=live，.env 中 ENABLE_LIVE_TRADING=true，"
            "并且 BINANCE_API_KEY / BINANCE_API_SECRET 已配置。"
        )


if __name__ == "__main__":
    main()
