from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: datetime
    volume: int = 0
    spread: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class Candle(BaseModel):
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: float = 0.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open


class SymbolInfo(BaseModel):
    symbol: str
    base_asset: str
    pip_size: float
    contract_size: float
    min_lot: float
    max_lot: float
    lot_step: float
    spread_typical: float
    commission_per_lot: float
    margin_currency: str


class AccountInfo(BaseModel):
    account_id: str
    balance: float
    equity: float
    free_margin: float
    margin_level: float
    leverage: int
    currency: str
    server_time: datetime


class ConnectionState(BaseModel):
    is_connected: bool = False
    is_synchronized: bool = False
    last_tick_time: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    reconnect_count: int = 0
    last_error: Optional[str] = None


class MarketSession(str, Enum):
    ASIA = "ASIA"
    EUROPE = "EUROPE"
    US = "US"
    CLOSED = "CLOSED"


class KinematicsData(BaseModel):
    symbol: str
    timestamp: datetime
    velocity: float
    acceleration: float
    jerk: float = 0.0
    phase: str = "UNKNOWN"
    eps_v: float = 0.0
    eps_a: float = 0.0
    atr_m1: float = 0.0
    atr_m5: float = 0.0
    atr_m15: float = 0.0
    gas_ratio: float = 0.0
    daily_high: float = 0.0
    daily_low: float = 0.0
    current_price: float = 0.0
    micro_phase: str = "FLAT"


class OrderRequest(BaseModel):
    symbol: str
    volume: float
    direction: Literal[1, -1]
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    magic: int = 20260510
    comment: str = ""


class Position(BaseModel):
    position_id: str
    symbol: str
    volume: float
    direction: Literal[1, -1]
    open_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    open_time: datetime
    magic: int = 0


class Order(BaseModel):
    order_id: str
    symbol: str
    volume: float
    direction: Literal[1, -1]
    order_type: str
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    state: str
    open_time: datetime
    magic: int = 0


class TradeRow(BaseModel):
    """
    B2a (CONTEXT_DEDUP_GATE): trade-row persistence model.
    
    APPEND-ONLY columns added to the `trades` SQLite table:
      context_gen       — int, default 0. Generation counter per (structure, strategy, side);
                          incremented on each close event (TP/SL settled).
      last_closed_ticket — str, default None. Ticket of the most recently closed trade,
                          used to restore context_gen after restart (B1 bootstrap).
      swing_anchor      — float, default None. K1: round(price, 1) — price-based anchor
                          (restart-stable, unlike swing_idx which reindexes on restart).
    
    Migration note:
      The `trades` table DDL lives in storage.py (_create_tables).
      For EXISTING databases, run:
        ALTER TABLE trades ADD COLUMN context_gen INTEGER DEFAULT 0;
        ALTER TABLE trades ADD COLUMN last_closed_ticket TEXT DEFAULT NULL;
        ALTER TABLE trades ADD COLUMN swing_anchor REAL DEFAULT NULL;
      SQLite ALTER TABLE ADD COLUMN is safe (O(1) for default values).
      save_trade() in storage.py must include these fields in the INSERT.
    """
    ticket_id: str
    symbol: str
    side: str
    lot: float
    entry_price: float
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    entry_time: int
    exit_time: Optional[int] = None
    close_reason: str = ""
    phase_at_entry: str = ""
    # B2a new columns (append-only)
    context_gen: int = 0
    last_closed_ticket: Optional[str] = None
    swing_anchor: Optional[float] = None