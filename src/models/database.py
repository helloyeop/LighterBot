from sqlalchemy import Column, String, Float, Integer, DateTime, Enum, Boolean, DECIMAL, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum

Base = declarative_base()


class OrderSide(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PositionSide(enum.Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class Trade(Base):
    __tablename__ = "trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum(OrderSide), nullable=False)
    quantity = Column(DECIMAL(20, 8), nullable=False)
    price = Column(DECIMAL(20, 8), nullable=False)
    status = Column(Enum(OrderStatus), nullable=False)
    order_id = Column(String(100), nullable=True)
    strategy = Column(String(50), nullable=True)
    pnl = Column(DECIMAL(20, 8), nullable=True)
    fee = Column(DECIMAL(20, 8), nullable=True)
    leverage = Column(Integer, default=1)
    stop_loss = Column(DECIMAL(20, 8), nullable=True)
    take_profit = Column(DECIMAL(20, 8), nullable=True)
    webhook_data = Column(JSON, nullable=True)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    side = Column(Enum(PositionSide), nullable=False)
    quantity = Column(DECIMAL(20, 8), nullable=False)
    entry_price = Column(DECIMAL(20, 8), nullable=False)
    current_price = Column(DECIMAL(20, 8), nullable=True)
    unrealized_pnl = Column(DECIMAL(20, 8), nullable=True)
    realized_pnl = Column(DECIMAL(20, 8), default=0)
    leverage = Column(Integer, default=1)
    status = Column(Enum(PositionStatus), nullable=False)
    stop_loss = Column(DECIMAL(20, 8), nullable=True)
    take_profit = Column(DECIMAL(20, 8), nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow)
    source_ip = Column(String(45), nullable=True)
    payload = Column(JSON, nullable=False)
    is_valid = Column(Boolean, default=False)
    processed = Column(Boolean, default=False)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RiskMetrics(Base):
    __tablename__ = "risk_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime, nullable=False)
    daily_trades_count = Column(Integer, default=0)
    daily_volume = Column(DECIMAL(20, 8), default=0)
    daily_pnl = Column(DECIMAL(20, 8), default=0)
    daily_loss = Column(DECIMAL(20, 8), default=0)
    max_drawdown = Column(DECIMAL(20, 8), default=0)
    win_rate = Column(Float, default=0)
    average_win = Column(DECIMAL(20, 8), default=0)
    average_loss = Column(DECIMAL(20, 8), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)