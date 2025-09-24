"""Strategy evaluators inspired by trading playbooks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.models import TradeSide


@dataclass
class StrategySignal:
    name: str
    side: TradeSide
    entry_price: float
    confidence: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    quantity: Optional[float] = None


def ema_trend_pullback(df: pd.DataFrame, confidence_boost: float = 0.0) -> Optional[StrategySignal]:
    """Trend-following pullback using dual EMA confirmation."""
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    bullish = (
        latest.ema_fast > latest.ema_slow
        and latest.close > latest.ema_trend
        and prev.close < prev.ema_fast <= latest.close
    )
    bearish = (
        latest.ema_fast < latest.ema_slow
        and latest.close < latest.ema_trend
        and prev.close > prev.ema_fast >= latest.close
    )

    if bullish:
        slope_strength = (latest.ema_fast - latest.ema_slow) / latest.ema_slow
        confidence = min(1.0, max(0.2, slope_strength * 8) + confidence_boost)
        return StrategySignal(
            name="ema_trend_pullback",
            side=TradeSide.BUY,
            entry_price=float(latest.close),
            confidence=confidence,
        )
    if bearish:
        slope_strength = (latest.ema_slow - latest.ema_fast) / latest.ema_slow
        confidence = min(1.0, max(0.2, slope_strength * 8) + confidence_boost)
        return StrategySignal(
            name="ema_trend_pullback",
            side=TradeSide.SELL,
            entry_price=float(latest.close),
            confidence=confidence,
        )
    return None


def volume_breakout(df: pd.DataFrame, lookback: int, volume_multiplier: float, buffer_pct: float) -> Optional[StrategySignal]:
    """Detect high-volume breakout/breakdown events."""
    if len(df) < lookback + 2:
        return None

    latest = df.iloc[-1]
    prior_window = df.iloc[-(lookback + 1):-1]

    resistance = prior_window["high"].max()
    support = prior_window["low"].min()
    vol_ma = prior_window["volume"].mean()

    breakout_up = latest.close > resistance * (1 + buffer_pct) and latest.volume >= vol_ma * volume_multiplier
    breakout_down = latest.close < support * (1 - buffer_pct) and latest.volume >= vol_ma * volume_multiplier

    if breakout_up:
        confidence = min(1.0, (latest.volume / max(vol_ma, 1e-9)) / volume_multiplier)
        return StrategySignal(
            name="volume_breakout",
            side=TradeSide.BUY,
            entry_price=float(latest.close),
            confidence=max(0.3, confidence),
            stop_loss=float(support),
        )
    if breakout_down:
        confidence = min(1.0, (latest.volume / max(vol_ma, 1e-9)) / volume_multiplier)
        return StrategySignal(
            name="volume_breakout",
            side=TradeSide.SELL,
            entry_price=float(latest.close),
            confidence=max(0.3, confidence),
            stop_loss=float(resistance),
        )
    return None


def rsi_divergence(
    df: pd.DataFrame,
    window: int,
    min_price_change_pct: float,
    min_rsi_change: float,
    bullish_floor: float,
    bearish_ceiling: float,
) -> Optional[StrategySignal]:
    """Identify RSI divergences using two rolling windows."""
    if len(df) < window * 2:
        return None

    recent = df.iloc[-window:]
    previous = df.iloc[-2 * window:-window]

    recent_low_idx = recent["close"].idxmin()
    prev_low_idx = previous["close"].idxmin()

    recent_high_idx = recent["close"].idxmax()
    prev_high_idx = previous["close"].idxmax()

    price_low_recent = df.loc[recent_low_idx, "close"]
    price_low_prev = df.loc[prev_low_idx, "close"]
    rsi_low_recent = df.loc[recent_low_idx, "rsi"]
    rsi_low_prev = df.loc[prev_low_idx, "rsi"]

    price_high_recent = df.loc[recent_high_idx, "close"]
    price_high_prev = df.loc[prev_high_idx, "close"]
    rsi_high_recent = df.loc[recent_high_idx, "rsi"]
    rsi_high_prev = df.loc[prev_high_idx, "rsi"]

    price_drop = (price_low_prev - price_low_recent) / max(price_low_prev, 1e-9)
    price_rise = (price_high_recent - price_high_prev) / max(price_high_prev, 1e-9)

    bullish = (
        price_low_recent < price_low_prev * (1 - min_price_change_pct)
        and rsi_low_recent > rsi_low_prev + min_rsi_change
        and rsi_low_recent <= bullish_floor
    )
    bearish = (
        price_high_recent > price_high_prev * (1 + min_price_change_pct)
        and rsi_high_recent < rsi_high_prev - min_rsi_change
        and rsi_high_recent >= bearish_ceiling
    )

    if bullish:
        confidence = min(1.0, abs(rsi_low_recent - rsi_low_prev) / max(min_rsi_change, 1e-9) * 0.5)
        return StrategySignal(
            name="rsi_divergence",
            side=TradeSide.BUY,
            entry_price=float(df.iloc[-1].close),
            confidence=max(0.25, confidence),
            stop_loss=float(min(price_low_recent, price_low_prev)),
        )
    if bearish:
        confidence = min(1.0, abs(rsi_high_prev - rsi_high_recent) / max(min_rsi_change, 1e-9) * 0.5)
        return StrategySignal(
            name="rsi_divergence",
            side=TradeSide.SELL,
            entry_price=float(df.iloc[-1].close),
            confidence=max(0.25, confidence),
            stop_loss=float(max(price_high_recent, price_high_prev)),
        )
    return None


def breakout_retest(df: pd.DataFrame, lookback: int, tolerance_pct: float, confirmation_bars: int) -> Optional[StrategySignal]:
    """Look for breakout followed by a successful retest within a tolerance band."""
    if len(df) < lookback + confirmation_bars + 2:
        return None

    latest = df.iloc[-1]
    zone_window = df.iloc[-(lookback + confirmation_bars + 1):-confirmation_bars]
    confirmation_window = df.iloc[-confirmation_bars:]

    resistance = zone_window["high"].max()
    support = zone_window["low"].min()

    breakout_up = (
        df.iloc[-confirmation_bars - 1]["close"] > resistance
        and confirmation_window["low"].min() >= resistance * (1 - tolerance_pct)
        and latest.close > resistance
    )
    breakout_down = (
        df.iloc[-confirmation_bars - 1]["close"] < support
        and confirmation_window["high"].max() <= support * (1 + tolerance_pct)
        and latest.close < support
    )

    if breakout_up:
        pullback_low = confirmation_window["low"].min()
        confidence = min(1.0, (latest.close - pullback_low) / max(resistance * tolerance_pct, 1e-9))
        return StrategySignal(
            name="breakout_retest",
            side=TradeSide.BUY,
            entry_price=float(latest.close),
            confidence=max(0.3, confidence),
            stop_loss=float(pullback_low * (1 - tolerance_pct)),
        )
    if breakout_down:
        pullback_high = confirmation_window["high"].max()
        confidence = min(1.0, (pullback_high - latest.close) / max(support * tolerance_pct, 1e-9))
        return StrategySignal(
            name="breakout_retest",
            side=TradeSide.SELL,
            entry_price=float(latest.close),
            confidence=max(0.3, confidence),
            stop_loss=float(pullback_high * (1 + tolerance_pct)),
        )
    return None


def macd_crossover(df: pd.DataFrame) -> Optional[StrategySignal]:
    """Traditional MACD signal cross."""
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    bullish = prev.macd < prev.macd_signal and latest.macd > latest.macd_signal
    bearish = prev.macd > prev.macd_signal and latest.macd < latest.macd_signal

    if bullish:
        strength = latest.macd - latest.macd_signal
        confidence = min(1.0, max(0.2, strength * 10))
        return StrategySignal(
            name="macd_crossover",
            side=TradeSide.BUY,
            entry_price=float(latest.close),
            confidence=confidence,
        )
    if bearish:
        strength = latest.macd_signal - latest.macd
        confidence = min(1.0, max(0.2, strength * 10))
        return StrategySignal(
            name="macd_crossover",
            side=TradeSide.SELL,
            entry_price=float(latest.close),
            confidence=confidence,
        )
    return None
*** End Patch
