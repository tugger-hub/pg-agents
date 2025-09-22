"""
SQLAlchemy ORM models for the database tables.
"""
from datetime import datetime
from sqlalchemy import (Column, DateTime, Index, Integer, BigInteger, Numeric, String,
                        UniqueConstraint)
from sqlalchemy.sql import func

from .database import Base


class Candle(Base):
    __tablename__ = "candles"

    id = Column(BigInteger, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False)
    timeframe = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Numeric, nullable=False)
    high = Column(Numeric, nullable=False)
    low = Column(Numeric, nullable=False)
    close = Column(Numeric, nullable=False)
    volume = Column(Numeric, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="ux_candles_symbol_tf_ts"),
        Index("idx_candles_symbol_timestamp", "symbol", timestamp.desc()),
    )

    def __repr__(self):
        return (
            f"<Candle(symbol='{self.symbol}', timeframe='{self.timeframe}', "
            f"timestamp='{self.timestamp}', close='{self.close}')>"
        )
