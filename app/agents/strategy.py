"""Strategy agent that evaluates multiple playbooks to generate trade decisions."""
from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.agents.base import Agent
from app.config import settings
from app.db_models import Candle
from app.models import TradingDecision, TradeSide
from app.strategies.indicators import prepare_indicators
from app.strategies import signals as strat_signals

logger = logging.getLogger(__name__)


@dataclass
class SignalContext:
    symbol: str
    strategy_name: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    side: TradeSide
    quantity: Optional[float]
    bar_timestamp: datetime


class StrategyAgent(Agent):
    """Aggregates several TA-based strategies to produce trading decisions."""

    def __init__(
        self,
        db_session: Session | Callable[[], Session],
        symbols: Iterable[str] | None = None,
        timeframe: Optional[str] = None,
    ) -> None:
        if isinstance(db_session, Session):
            self._session_factory: Callable[[], Session] = lambda: db_session
            self._manage_session = False
        else:
            self._session_factory = db_session  # type: ignore[assignment]
            self._manage_session = True

        self.symbols = list(symbols or settings.trading_symbols)
        self.timeframe = timeframe or settings.strategy.timeframes.entry
        self.config = settings.strategy
        self.logger = logging.getLogger(self.__class__.__name__)
        self._last_signal_at: dict[str, datetime] = {}
        self._last_signal_bar: dict[str, datetime] = {}

        self._min_history = max(
            self.config.moving_average.trend_period + 5,
            self.config.risk_management.atr_period + 5,
            self.config.divergence.window * 2,
        )

    @contextmanager
    def _session_scope(self):
        session = self._session_factory()
        try:
            yield session
        finally:
            if self._manage_session:
                session.close()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def run(self) -> List[TradingDecision]:
        decisions: List[TradingDecision] = []

        with self._session_scope() as session:
            for symbol in self.symbols:
                candles = self._fetch_recent_candles(session, symbol)
                if not candles:
                    self.logger.debug("Insufficient candles for %s", symbol)
                    continue

                signal = self._evaluate_symbol(symbol, candles)
                if not signal:
                    continue

                decision = TradingDecision(
                    symbol=symbol,
                    side=signal.side,
                    quantity=signal.quantity,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    confidence=signal.confidence,
                )
                decisions.append(decision)
                self._last_signal_at[symbol] = datetime.now(timezone.utc)
                self._last_signal_bar[symbol] = signal.bar_timestamp
                self.logger.info(
                    "Strategy %s generated %s for %s @ %.2f (SL %.2f / TP %.2f / qty %s)",
                    signal.strategy_name,
                    signal.side.value,
                    symbol,
                    signal.entry_price,
                    signal.stop_loss,
                    signal.take_profit,
                    f"{signal.quantity:.6f}" if signal.quantity else "auto",
                )

        if not decisions:
            self.logger.debug("No strategy signals generated in this cycle.")

        return decisions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_recent_candles(self, session: Session, symbol: str) -> List[Candle]:
        query = (
            session.query(Candle)
            .filter(Candle.symbol == symbol, Candle.timeframe == self.timeframe)
            .order_by(Candle.timestamp.desc())
            .limit(self._min_history)
        )
        candles = list(reversed(query.all()))
        if len(candles) < self._min_history:
            return []
        return candles

    def _evaluate_symbol(self, symbol: str, candles: List[Candle]) -> Optional[SignalContext]:
        last_bar = candles[-1]
        if last_bar.timestamp is None:
            return None

        if self._last_signal_bar.get(symbol) == last_bar.timestamp:
            return None

        cooldown = timedelta(seconds=self.config.signal_confidence.cooldown_seconds)
        last_signal_at = self._last_signal_at.get(symbol)
        if last_signal_at and datetime.now(timezone.utc) - last_signal_at < cooldown:
            return None

        df = self._candles_to_dataframe(candles)
        bundle = prepare_indicators(
            df,
            ema_fast_period=self.config.moving_average.fast_period,
            ema_slow_period=self.config.moving_average.slow_period,
            ema_trend_period=self.config.moving_average.trend_period,
            atr_period=self.config.risk_management.atr_period,
            rsi_period=self.config.divergence.rsi_period,
            macd_fast=self.config.macd.fast_period,
            macd_slow=self.config.macd.slow_period,
            macd_signal=self.config.macd.signal_period,
        )

        enriched = bundle.df.dropna(subset=[
            "ema_fast",
            "ema_slow",
            "ema_trend",
            "atr",
            "rsi",
            "macd",
            "macd_signal",
        ])
        if enriched.empty:
            return None

        signals: List[strat_signals.StrategySignal] = []
        switches = self.config.switches

        if switches.ema_trend_pullback:
            sig = strat_signals.ema_trend_pullback(enriched)
            if sig:
                signals.append(sig)

        if switches.volume_breakout:
            sig = strat_signals.volume_breakout(
                enriched,
                lookback=self.config.volume_breakout.lookback,
                volume_multiplier=self.config.volume_breakout.volume_multiplier,
                buffer_pct=self.config.volume_breakout.breakout_buffer_pct,
            )
            if sig:
                signals.append(sig)

        if switches.rsi_divergence:
            sig = strat_signals.rsi_divergence(
                enriched,
                window=self.config.divergence.window,
                min_price_change_pct=self.config.divergence.min_price_change_pct,
                min_rsi_change=self.config.divergence.min_rsi_change,
                bullish_floor=self.config.divergence.bullish_rsi_floor,
                bearish_ceiling=self.config.divergence.bearish_rsi_ceiling,
            )
            if sig:
                signals.append(sig)

        if switches.breakout_retest:
            sig = strat_signals.breakout_retest(
                enriched,
                lookback=self.config.retest.lookback,
                tolerance_pct=self.config.retest.tolerance_pct,
                confirmation_bars=self.config.retest.confirmation_bars,
            )
            if sig:
                signals.append(sig)

        if switches.macd_crossover:
            sig = strat_signals.macd_crossover(enriched)
            if sig:
                signals.append(sig)

        if not signals:
            return None

        grouped: dict[TradeSide, List[strat_signals.StrategySignal]] = {}
        for sig in signals:
            grouped.setdefault(sig.side, []).append(sig)

        best_signal: Optional[strat_signals.StrategySignal] = None
        best_confidence = 0.0
        for side, sigs in grouped.items():
            sigs_sorted = sorted(sigs, key=lambda s: s.confidence, reverse=True)
            top = sigs_sorted[0]
            boost = min(0.2, 0.05 * (len(sigs) - 1))
            adjusted_conf = min(1.0, top.confidence + boost)
            if adjusted_conf > best_confidence:
                best_confidence = adjusted_conf
                best_signal = strat_signals.StrategySignal(
                    name=top.name,
                    side=top.side,
                    entry_price=top.entry_price,
                    confidence=adjusted_conf,
                    stop_loss=top.stop_loss,
                    take_profit=top.take_profit,
                    quantity=top.quantity,
                )

        if not best_signal:
            return None

        atr_value = float(enriched["atr"].iloc[-1])
        if not math.isfinite(atr_value) or atr_value <= 0:
            atr_value = None
        stop_loss = best_signal.stop_loss
        if stop_loss is None:
            stop_loss = self._calculate_stop_loss(best_signal.entry_price, atr_value, best_signal.side)
            if stop_loss is None:
                return None

        take_profit = best_signal.take_profit
        if take_profit is None:
            take_profit = self._calculate_take_profit(best_signal.entry_price, stop_loss, best_signal.side)

        risk_per_unit = abs(best_signal.entry_price - stop_loss)
        if risk_per_unit <= 0:
            return None

        quantity = best_signal.quantity
        if quantity is None:
            quantity = self._size_position(best_signal.entry_price, risk_per_unit)

        if best_confidence < self.config.signal_confidence.threshold:
            return None

        return SignalContext(
            symbol=symbol,
            strategy_name=best_signal.name,
            entry_price=best_signal.entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=best_confidence,
            side=best_signal.side,
            quantity=quantity,
            bar_timestamp=last_bar.timestamp,
        )

    def _calculate_stop_loss(self, entry_price: float, atr: Optional[float], side: TradeSide) -> Optional[float]:
        cfg = self.config.risk_management
        offset = None
        if cfg.stop_loss_method == "atr" and atr:
            offset = atr * cfg.atr_multiplier
        elif cfg.stop_loss_method == "percentage":
            offset = entry_price * (cfg.percentage_sl / 100)
        else:
            offset = atr * cfg.atr_multiplier if atr else entry_price * (cfg.percentage_sl / 100)

        if not offset or offset <= 0:
            return None

        if side == TradeSide.BUY:
            return max(entry_price - offset, 0.0)
        return entry_price + offset

    def _calculate_take_profit(self, entry_price: float, stop_loss: float, side: TradeSide) -> float:
        cfg = self.config.risk_management
        risk = abs(entry_price - stop_loss)
        reward = risk * max(cfg.atr_take_profit_r_multiple, 1.0)
        if side == TradeSide.BUY:
            return entry_price + reward
        return max(entry_price - reward, 0.0)

    def _size_position(self, entry_price: float, risk_per_unit: float) -> Optional[float]:
        sizing = self.config.position_sizing
        equity = sizing.account_equity_usd or self.config.risk_management.account_equity_usd
        risk_percent = sizing.risk_per_trade_percent or self.config.default_risk.ratio
        risk_amount = equity * (risk_percent / 100)

        if risk_amount <= 0 or risk_per_unit <= 0:
            return None

        quantity = risk_amount / risk_per_unit

        if sizing.max_position_notional_usd:
            max_qty = sizing.max_position_notional_usd / entry_price
            quantity = min(quantity, max_qty)
        if sizing.min_position_notional_usd:
            min_qty = sizing.min_position_notional_usd / entry_price
            quantity = max(quantity, min_qty)

        return round(quantity, 8) if quantity > 0 else None

    @staticmethod
    def _candles_to_dataframe(candles: List[Candle]) -> pd.DataFrame:
        data = {
            "timestamp": [c.timestamp for c in candles],
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        }
        df = pd.DataFrame(data)
        df.set_index("timestamp", inplace=True)
        return df


def some_pure_strategy_function(price: float, moving_average: float) -> TradeSide | None:
    """Legacy pure function kept for unit testing."""
    if price > moving_average:
        return TradeSide.BUY
    if price < moving_average:
        return TradeSide.SELL
    return None
*** End Patch
