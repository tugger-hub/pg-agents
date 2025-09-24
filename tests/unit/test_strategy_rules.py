import numpy as np
import pandas as pd
import pytest

from app.models import TradeSide
from app.strategies.signals import (
    ema_trend_pullback,
    volume_breakout,
    rsi_divergence,
)


def _base_df(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=rows, freq="T")
    df = pd.DataFrame({
        "open": [100.0] * rows,
        "high": [101.0] * rows,
        "low": [99.0] * rows,
        "close": [100.0] * rows,
        "volume": [1_000.0] * rows,
        "ema_fast": [100.0] * rows,
        "ema_slow": [100.0] * rows,
        "ema_trend": [100.0] * rows,
        "atr": [1.0] * rows,
        "rsi": [50.0] * rows,
        "macd": [0.0] * rows,
        "macd_signal": [0.0] * rows,
    }, index=idx)
    return df


def test_ema_trend_pullback_generates_buy_signal():
    df = _base_df(5)
    df.iloc[-2, df.columns.get_loc("close")] = 101.0
    df.iloc[-2, df.columns.get_loc("ema_fast")] = 102.0
    df.iloc[-1, df.columns.get_loc("close")] = 104.0
    df.iloc[-1, df.columns.get_loc("ema_fast")] = 104.5
    df.iloc[-1, df.columns.get_loc("ema_slow")] = 102.0
    df.iloc[-1, df.columns.get_loc("ema_trend")] = 100.0
    signal = ema_trend_pullback(df)
    assert signal is not None
    assert signal.side == TradeSide.BUY
    assert signal.confidence > 0


def test_volume_breakout_detects_high_volume_breakout():
    rows = 25
    df = _base_df(rows)
    df.iloc[:-1, df.columns.get_loc("high")] = [100 + i * 0.05 for i in range(rows - 1)]
    df.iloc[:-1, df.columns.get_loc("close")] = [100 + i * 0.02 for i in range(rows - 1)]
    df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[:-1].max() + 1.0
    df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[:-1].mean() * 3
    signal = volume_breakout(df, lookback=20, volume_multiplier=2.0, buffer_pct=0.0)
    assert signal is not None
    assert signal.side == TradeSide.BUY
    assert signal.stop_loss is not None


def test_rsi_divergence_identifies_bullish_setup():
    window = 20
    rows = window * 2
    df = _base_df(rows)

    # Previous window trending down with lower RSI
    prev_closes = pd.Series(np.linspace(100, 85, window))
    prev_rsi = pd.Series(np.linspace(35, 25, window))
    df.iloc[:window, df.columns.get_loc("close")] = prev_closes.values
    df.iloc[:window, df.columns.get_loc("rsi")] = prev_rsi.values

    # Recent window makes a marginal lower low but RSI rises
    recent_closes = pd.Series(np.linspace(84, 82, window))
    recent_closes.iloc[-1] = 80.0
    recent_rsi = pd.Series(np.linspace(30, 40, window))
    recent_rsi.iloc[-1] = 36.0
    df.iloc[window:, df.columns.get_loc("close")] = recent_closes.values
    df.iloc[window:, df.columns.get_loc("rsi")] = recent_rsi.values

    signal = rsi_divergence(
        df,
        window=window,
        min_price_change_pct=0.01,
        min_rsi_change=2.0,
        bullish_floor=45.0,
        bearish_ceiling=55.0,
    )
    assert signal is not None
    assert signal.side == TradeSide.BUY
    assert signal.confidence >= 0.25
*** End Patch
