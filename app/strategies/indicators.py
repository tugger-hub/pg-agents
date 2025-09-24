"""Indicator utility functions used across strategy evaluators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class IndicatorBundle:
    df: pd.DataFrame
    atr: pd.Series
    rsi: pd.Series
    ema_fast: pd.Series
    ema_slow: pd.Series
    ema_trend: pd.Series
    macd: pd.Series
    macd_signal: pd.Series


def prepare_indicators(
    candles: pd.DataFrame,
    ema_fast_period: int,
    ema_slow_period: int,
    ema_trend_period: int,
    atr_period: int,
    rsi_period: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
) -> IndicatorBundle:
    """Return dataframe enriched with indicators commonly used by strategies."""
    df = candles.copy()

    df["ema_fast"] = _ema(df["close"], ema_fast_period)
    df["ema_slow"] = _ema(df["close"], ema_slow_period)
    df["ema_trend"] = _ema(df["close"], ema_trend_period)

    true_range = _true_range(df)
    df["atr"] = _ema(true_range, atr_period)

    df["rsi"] = _rsi(df["close"], period=rsi_period)

    macd_line, signal_line = _macd(df["close"], macd_fast, macd_slow, macd_signal)
    df["macd"] = macd_line
    df["macd_signal"] = signal_line

    return IndicatorBundle(
        df=df,
        atr=df["atr"],
        rsi=df["rsi"],
        ema_fast=df["ema_fast"],
        ema_slow=df["ema_slow"],
        ema_trend=df["ema_trend"],
        macd=df["macd"],
        macd_signal=df["macd_signal"],
    )


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    gain_ema = pd.Series(gain, index=series.index).ewm(alpha=1 / period, adjust=False).mean()
    loss_ema = pd.Series(loss, index=series.index).ewm(alpha=1 / period, adjust=False).mean()

    rs = gain_ema / loss_ema.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _macd(series: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    fast_ema = _ema(series, fast)
    slow_ema = _ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line
*** End Patch
