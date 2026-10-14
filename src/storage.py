import sqlite3
import asyncio
import shutil
import aiosqlite
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from src.models import (
    Tick, Candle, SymbolInfo, AccountInfo,
    Timeframe, KinematicsData, Position, Order
)

logger = logging.getLogger(__name__)


class SQLiteStorage:
    def __init__(self, db_path: str = "data/scalp5.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        self._pool = await aiosqlite.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None
        )
        await self._pool.execute("PRAGMA journal_mode=WAL")
        await self._pool.execute("PRAGMA synchronous=NORMAL")
        await self._pool.execute("PRAGMA cache_size=-32768")
        await self._pool.execute("PRAGMA temp_store=MEMORY")
        await self._pool.execute("PRAGMA mmap_size=268435456")
        await self._create_tables()
        await self._create_indexes()
        logger.info(f"[STORAGE] SQLite WAL initialized: {self.db_path}")

    async def _create_tables(self):
        schema = """
        CREATE TABLE IF NOT EXISTS ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            bid REAL NOT NULL,
            ask REAL NOT NULL,
            timestamp INTEGER NOT NULL,
            volume INTEGER DEFAULT 0,
            spread REAL DEFAULT 0.0,
            received_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            tick_volume INTEGER DEFAULT 0,
            spread REAL DEFAULT 0.0,
            is_final INTEGER DEFAULT 1,
            UNIQUE(symbol, timeframe, timestamp)
        );

        CREATE TABLE IF NOT EXISTS symbol_info (
            symbol TEXT PRIMARY KEY,
            base_asset TEXT NOT NULL,
            pip_size REAL NOT NULL,
            contract_size REAL NOT NULL,
            min_lot REAL NOT NULL,
            max_lot REAL NOT NULL,
            lot_step REAL NOT NULL,
            spread_typical REAL NOT NULL,
            commission_per_lot REAL NOT NULL,
            margin_currency TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            balance REAL NOT NULL,
            equity REAL NOT NULL,
            free_margin REAL NOT NULL,
            margin_level REAL NOT NULL,
            leverage INTEGER NOT NULL,
            currency TEXT NOT NULL,
            server_time INTEGER NOT NULL,
            captured_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS kinematics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            velocity REAL NOT NULL,
            acceleration REAL NOT NULL,
            jerk REAL DEFAULT 0.0,
            phase TEXT DEFAULT 'UNKNOWN',
            eps_v REAL DEFAULT 0.0,
            eps_a REAL DEFAULT 0.0,
            atr_m1 REAL DEFAULT 0.0,
            atr_m5 REAL DEFAULT 0.0,
            atr_m15 REAL DEFAULT 0.0,
            gas_ratio REAL DEFAULT 0.0,
            daily_high REAL DEFAULT 0.0,
            daily_low REAL DEFAULT 0.0,
            UNIQUE(symbol, timestamp)
        );

        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            volume REAL NOT NULL,
            direction INTEGER NOT NULL,
            open_price REAL NOT NULL,
            current_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            unrealized_pnl REAL DEFAULT 0.0,
            commission REAL DEFAULT 0.0,
            swap REAL DEFAULT 0.0,
            open_time INTEGER NOT NULL,
            magic INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            volume REAL NOT NULL,
            direction INTEGER NOT NULL,
            order_type TEXT NOT NULL,
            price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            state TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            magic INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS trades (
            ticket_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            lot REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            stop_loss REAL,
            take_profit REAL,
            commission REAL DEFAULT 0.0,
            swap REAL DEFAULT 0.0,
            gross_pnl REAL DEFAULT 0.0,
            net_pnl REAL DEFAULT 0.0,
            max_favorable_excursion REAL DEFAULT 0.0,
            max_adverse_excursion REAL DEFAULT 0.0,
            entry_time INTEGER NOT NULL,
            exit_time INTEGER,
            duration_seconds INTEGER DEFAULT 0,
            close_reason TEXT,
            phase_at_entry TEXT,
            kinematics_at_entry TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            open_price REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            close_price REAL NOT NULL,
            tick_volume INTEGER DEFAULT 0,
            realized_pnl REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            trade_count INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS swing_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            price REAL NOT NULL,
            swing_type TEXT NOT NULL,
            phase TEXT DEFAULT '',
            strength REAL DEFAULT 0.0,
            volume REAL DEFAULT 0.0,
            z_v REAL DEFAULT 0.0,
            z_a REAL DEFAULT 0.0,
            UNIQUE(symbol, timestamp)
        );

        CREATE TABLE IF NOT EXISTS swing_fractal (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            price REAL NOT NULL,
            swing_type TEXT NOT NULL CHECK(swing_type IN ('high','low')),
            UNIQUE(symbol, timeframe, timestamp)
        );

        -- KNOWN-EMPTY-GAP (finding F2, 2026-09-22): gaps the broker answered
        -- "0 candles" for (session-close/rollover windows). Recorded so the
        -- next startup skips them with 0 API calls instead of re-fetching.
        CREATE TABLE IF NOT EXISTS gap_markers (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            gap_start INTEGER NOT NULL,
            gap_end INTEGER NOT NULL,
            marked_at INTEGER NOT NULL,
            UNIQUE(symbol, timeframe, gap_start, gap_end)
        );
        """
        await self._pool.executescript(schema)

    async def _create_indexes(self):
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_time ON candles(symbol, timeframe, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_kinematics_symbol_time ON kinematics(symbol, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_orders_symbol_state ON orders(symbol, state)",
            "CREATE INDEX IF NOT EXISTS idx_account_snapshots_time ON account_snapshots(captured_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_daily_stats_symbol_date ON daily_stats(symbol, date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_swing_points_symbol_time ON swing_points(symbol, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_swing_fractal_tf_time ON swing_fractal(symbol, timeframe, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_gap_markers_symbol_tf ON gap_markers(symbol, timeframe)",
            "CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, entry_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_trades_close_reason ON trades(close_reason)",
            "CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time DESC)",
        ]
        for idx in indexes:
            await self._pool.execute(idx)
        await self._pool.commit()

    @asynccontextmanager
    async def transaction(self):
        await self._pool.execute("BEGIN")
        try:
            yield
            await self._pool.commit()
        except Exception:
            await self._pool.rollback()
            raise

    async def insert_tick(self, tick: Tick):
        await self._pool.execute(
            """INSERT INTO ticks (symbol, bid, ask, timestamp, volume, spread)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tick.symbol, tick.bid, tick.ask,
             int(tick.timestamp.timestamp()), tick.volume, tick.spread)
        )

    async def get_tick_timestamps(self, symbol: str, since: datetime) -> List[int]:
        """Epoch seconds of stored ticks for symbol since `since` (V2 td warmup seed)."""
        cursor = await self._pool.execute(
            "SELECT timestamp FROM ticks WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp",
            (symbol, int(since.timestamp())),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def insert_ticks_batch(self, ticks: List[Tick]):
        if not ticks:
            return
        await self._pool.executemany(
            """INSERT INTO ticks (symbol, bid, ask, timestamp, volume, spread)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(t.symbol, t.bid, t.ask, int(t.timestamp.timestamp()), t.volume, t.spread) for t in ticks]
        )
        await self._pool.commit()

    async def purge_old_ticks(self, days: int = 7) -> int:
        """Delete raw ticks older than `days` (keep candles + kinematics)."""
        cutoff = int(datetime.now(timezone.utc).timestamp()) - days * 86400
        cursor = await self._pool.execute(
            "DELETE FROM ticks WHERE timestamp < ?", (cutoff,)
        )
        await self._pool.commit()
        deleted = cursor.rowcount
        logger.info(f"[STORAGE] Purged {deleted} ticks older than {days} days")
        return deleted

    async def purge_old_candles(self, timeframe: Timeframe, days: int) -> int:
        """Delete candles of one timeframe older than `days`.

        Timestamp is epoch-seconds (int). H1/D1 are intentionally NOT purged —
        they are the structural/macro reference and must be kept indefinitely.
        """
        cutoff = int(datetime.now(timezone.utc).timestamp()) - days * 86400
        cursor = await self._pool.execute(
            "DELETE FROM candles WHERE timeframe = ? AND timestamp < ?",
            (timeframe.value, cutoff),
        )
        await self._pool.commit()
        deleted = cursor.rowcount
        logger.info(f"[STORAGE] Purged {deleted} {timeframe.value} candles older than {days} days")
        return deleted

    async def run_vacuum(self) -> None:
        """Reclaim disk space. Full DB rewrite — guard against low disk space."""
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        try:
            free = shutil.disk_usage(self.db_path.parent).free
        except OSError:
            free = 0
        if free > 0 and size > 0 and free < size * 2:
            logger.warning(
                f"[STORAGE] Skipping VACUUM: free={free / 1e6:.0f}MB < 2x db={size / 1e6:.0f}MB "
                "(VACUUM needs ~2x db size temporarily)"
            )
            return
        await self._pool.execute("VACUUM")
        await self._pool.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.info("[STORAGE] VACUUM + WAL checkpoint complete")

    async def purge_old_data(
        self, ticks_days: int = 7, m1_days: int = 14, vacuum: bool = True
    ) -> dict:
        """Unified daily purge job (00:00 UTC): ticks 7d, M1 candles 14d, H1/D1 kept.

        Returns per-table delete counts. VACUUM only when requested.
        """
        result = {
            "ticks": await self.purge_old_ticks(days=ticks_days),
            "m1_candles": await self.purge_old_candles(Timeframe.M1, days=m1_days),
        }
        if vacuum:
            await self.run_vacuum()
        return result

    async def insert_candle(self, candle: Candle):
        await self._pool.execute(
            """INSERT OR REPLACE INTO candles
               (symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread, is_final)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candle.symbol, candle.timeframe.value, int(candle.timestamp.timestamp()),
             candle.open, candle.high, candle.low, candle.close,
             candle.tick_volume, candle.spread, 1)
        )
        await self._pool.commit()

    async def insert_candles_batch(self, candles: List[Candle]):
        if not candles:
            return
        await self._pool.executemany(
            """INSERT OR REPLACE INTO candles
               (symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread, is_final)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(c.symbol, c.timeframe.value, int(c.timestamp.timestamp()),
              c.open, c.high, c.low, c.close, c.tick_volume, c.spread, 1) for c in candles]
        )
        await self._pool.commit()

    # [KNOWN-EMPTY-GAP F2, 2026-09-22] Marker store: a gap window the broker
    # answered "0 candles" for (session-close/rollover). Skipped with 0 API
    # calls on later startups.

    async def mark_gap_resolved(
        self, symbol: str, timeframe: Timeframe,
        gap_start: datetime, gap_end: datetime
    ) -> None:
        """Record that the broker has no data for [gap_start, gap_end)."""
        await self._pool.execute(
            """INSERT OR IGNORE INTO gap_markers
               (symbol, timeframe, gap_start, gap_end, marked_at)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol, timeframe.value, int(gap_start.timestamp()),
             int(gap_end.timestamp()), int(datetime.now(timezone.utc).timestamp()))
        )
        await self._pool.commit()

    async def get_resolved_gaps(
        self, symbol: str, timeframe: Timeframe
    ) -> set:
        """Return {(gap_start, gap_end)} marker tuples for this symbol/TF."""
        cursor = await self._pool.execute(
            "SELECT gap_start, gap_end FROM gap_markers "
            "WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe.value)
        )
        rows = await cursor.fetchall()
        return {
            (datetime.fromtimestamp(r[0], tz=timezone.utc),
             datetime.fromtimestamp(r[1], tz=timezone.utc))
            for r in rows
        }

    async def get_candles(
        self, symbol: str, timeframe: Timeframe,
        limit: int = 100, before: Optional[datetime] = None
    ) -> List[Candle]:
        if before:
            cursor = await self._pool.execute(
                """SELECT symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread
                   FROM candles
                   WHERE symbol = ? AND timeframe = ? AND timestamp < ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (symbol, timeframe.value, int(before.timestamp()), limit)
            )
        else:
            cursor = await self._pool.execute(
                """SELECT symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread
                   FROM candles
                   WHERE symbol = ? AND timeframe = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (symbol, timeframe.value, limit)
            )
        rows = await cursor.fetchall()
        return [
            Candle(
                symbol=r[0], timeframe=Timeframe(r[1]),
                timestamp=datetime.fromtimestamp(r[2], tz=timezone.utc),
                open=r[3], high=r[4], low=r[5], close=r[6],
                tick_volume=r[7], spread=r[8]
            )
            for r in reversed(rows)
        ]

    async def count_candles(self, symbol: str, timeframe: Timeframe,
                           since_epoch: int = 0) -> int:
        """FIX-1 (2026-09-22): candle count since unixepoch — ENSURE-HISTORY
        preflight check (verify enough history per TF before strategy start)."""
        cursor = await self._pool.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ? AND timeframe = ? AND timestamp >= ?",
            (symbol, timeframe.value, int(since_epoch))
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        cursor = await self._pool.execute(
            """SELECT symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread
               FROM candles
               WHERE symbol = ? AND timeframe = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (symbol, timeframe.value)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Candle(
            symbol=row[0], timeframe=Timeframe(row[1]),
            timestamp=datetime.fromtimestamp(row[2], tz=timezone.utc),
            open=row[3], high=row[4], low=row[5], close=row[6],
            tick_volume=row[7], spread=row[8]
        )

    async def insert_kinematics(self, k: KinematicsData):
        await self._pool.execute(
            """INSERT OR REPLACE INTO kinematics
               (symbol, timestamp, velocity, acceleration, jerk, phase, eps_v, eps_a,
                atr_m1, atr_m5, atr_m15, gas_ratio, daily_high, daily_low)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (k.symbol, int(k.timestamp.timestamp()), k.velocity, k.acceleration,
             k.jerk, k.phase, k.eps_v, k.eps_a, k.atr_m1, k.atr_m5, k.atr_m15,
             k.gas_ratio, k.daily_high, k.daily_low)
        )
        await self._pool.commit()

    async def upsert_symbol_info(self, info: SymbolInfo):
        await self._pool.execute(
            """INSERT OR REPLACE INTO symbol_info
               (symbol, base_asset, pip_size, contract_size, min_lot, max_lot,
                lot_step, spread_typical, commission_per_lot, margin_currency, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (info.symbol, info.base_asset, info.pip_size, info.contract_size,
             info.min_lot, info.max_lot, info.lot_step, info.spread_typical,
             info.commission_per_lot, info.margin_currency,
             int(datetime.now(timezone.utc).timestamp()))
        )
        await self._pool.commit()

    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        cursor = await self._pool.execute(
            "SELECT * FROM symbol_info WHERE symbol = ?", (symbol,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return SymbolInfo(
            symbol=row[0], base_asset=row[1], pip_size=row[2],
            contract_size=row[3], min_lot=row[4], max_lot=row[5],
            lot_step=row[6], spread_typical=row[7], commission_per_lot=row[8],
            margin_currency=row[9]
        )

    async def insert_account_snapshot(self, acc: AccountInfo):
        await self._pool.execute(
            """INSERT INTO account_snapshots
               (account_id, balance, equity, free_margin, margin_level, leverage, currency, server_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (acc.account_id, acc.balance, acc.equity, acc.free_margin,
             acc.margin_level, acc.leverage, acc.currency,
             int(acc.server_time.timestamp()))
        )
        await self._pool.commit()

    async def upsert_position(self, pos: Position):
        await self._pool.execute(
            """INSERT OR REPLACE INTO positions
               (position_id, symbol, volume, direction, open_price, current_price,
                stop_loss, take_profit, unrealized_pnl, commission, swap, open_time, magic, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pos.position_id, pos.symbol, pos.volume, pos.direction,
             pos.open_price, pos.current_price, pos.stop_loss, pos.take_profit,
             pos.unrealized_pnl, pos.commission, pos.swap,
             int(pos.open_time.timestamp()), pos.magic,
             int(datetime.now(timezone.utc).timestamp()))
        )
        await self._pool.commit()

    async def upsert_order(self, order: Order):
        await self._pool.execute(
            """INSERT OR REPLACE INTO orders
               (order_id, symbol, volume, direction, order_type, price,
                stop_loss, take_profit, state, open_time, magic, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order.order_id, order.symbol, order.volume, order.direction,
             order.order_type, order.price, order.stop_loss, order.take_profit,
             order.state, int(order.open_time.timestamp()), order.magic,
             int(datetime.now(timezone.utc).timestamp()))
        )
        await self._pool.commit()

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        if symbol:
            cursor = await self._pool.execute(
                "SELECT * FROM positions WHERE symbol = ?", (symbol,)
            )
        else:
            cursor = await self._pool.execute("SELECT * FROM positions")
        rows = await cursor.fetchall()
        return [
            Position(
                position_id=r[0], symbol=r[1], volume=r[2], direction=r[3],
                open_price=r[4], current_price=r[5], stop_loss=r[6],
                take_profit=r[7], unrealized_pnl=r[8], commission=r[9],
                swap=r[10], open_time=datetime.fromtimestamp(r[11], tz=timezone.utc),
                magic=r[12]
            ) for r in rows
        ]

    async def get_active_orders(self, symbol: Optional[str] = None) -> List[Order]:
        if symbol:
            cursor = await self._pool.execute(
                "SELECT * FROM orders WHERE symbol = ? AND state IN ('PLACED', 'PARTIAL')", (symbol,)
            )
        else:
            cursor = await self._pool.execute(
                "SELECT * FROM orders WHERE state IN ('PLACED', 'PARTIAL')"
            )
        rows = await cursor.fetchall()
        return [
            Order(
                order_id=r[0], symbol=r[1], volume=r[2], direction=r[3],
                order_type=r[4], price=r[5], stop_loss=r[6], take_profit=r[7],
                state=r[8], open_time=datetime.fromtimestamp(r[9], tz=timezone.utc),
                magic=r[10]
            ) for r in rows
        ]

    async def insert_swing_point(
        self, symbol: str, timestamp: int, price: float, swing_type: str,
        phase: str = "", strength: float = 0.0, volume: float = 0.0,
        z_v: float = 0.0, z_a: float = 0.0
    ) -> None:
        """SP-3: Upsert a swing point (UNIQUE(symbol, timestamp))."""
        await self._pool.execute(
            """INSERT OR REPLACE INTO swing_points
               (symbol, timestamp, price, swing_type, phase, strength, volume, z_v, z_a)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, timestamp, price, swing_type, phase, strength, volume, z_v, z_a)
        )
        await self._pool.commit()

    async def get_last_swings(self, symbol: str, limit: int = 20) -> list:
        """SP-3: Load recent swing points (chronological) for state restoration."""
        cursor = await self._pool.execute(
            """SELECT timestamp, price, swing_type, phase, strength, volume, z_v, z_a
               FROM swing_points WHERE symbol = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, limit)
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))

    async def upsert_swing_fractal(
        self, symbol: str, timeframe: str, timestamp: int, price: float,
        swing_type: str,
    ) -> None:
        """CYCLE-RANGE Phase 1: upsert a fractal swing into swing_fractal
        (UNIQUE(symbol, timeframe, timestamp) → idempotent)."""
        await self._pool.execute(
            """INSERT OR REPLACE INTO swing_fractal
               (symbol, timeframe, timestamp, price, swing_type)
               VALUES (?, ?, ?, ?, ?)""",
            (symbol, timeframe, timestamp, price, swing_type)
        )
        await self._pool.commit()

    async def get_swing_fractals(
        self, symbol: str, timeframe: str, limit: int = 80,
    ) -> list:
        """CYCLE-RANGE: load fractal swings (chronological, oldest→newest)."""
        cursor = await self._pool.execute(
            """SELECT timestamp, price, swing_type FROM swing_fractal
               WHERE symbol = ? AND timeframe = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, timeframe, limit)
        )
        rows = await cursor.fetchall()
        return list(reversed(rows))

    async def set_state(self, key: str, value: Any):
        await self._pool.execute(
            "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), int(datetime.now(timezone.utc).timestamp()))
        )
        await self._pool.commit()

    async def get_state(self, key: str, default: Any = None) -> Any:
        cursor = await self._pool.execute("SELECT value FROM system_state WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if not row:
            return default
        return json.loads(row[0])

    async def save_trade(self, trade: dict) -> None:
        """Save closed trade to trade_history table."""
        await self._pool.execute(
            """INSERT OR REPLACE INTO trades
               (ticket_id, symbol, side, lot, entry_price, exit_price,
                stop_loss, take_profit, commission, swap, gross_pnl, net_pnl,
                max_favorable_excursion, max_adverse_excursion,
                entry_time, exit_time, duration_seconds, close_reason,
                phase_at_entry, kinematics_at_entry)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.get("ticket_id", ""),
                trade.get("symbol", ""),
                trade.get("side", ""),
                trade.get("lot", 0.0),
                trade.get("entry_price", 0.0),
                trade.get("exit_price", 0.0),
                trade.get("stop_loss", 0.0),
                trade.get("take_profit", 0.0),
                trade.get("commission", 0.0),
                trade.get("swap", 0.0),
                trade.get("gross_pnl", 0.0),
                trade.get("net_pnl", 0.0),
                trade.get("max_favorable_excursion", 0.0),
                trade.get("max_adverse_excursion", 0.0),
                trade.get("entry_time", 0),
                trade.get("exit_time", 0),
                trade.get("duration_seconds", 0),
                trade.get("close_reason", ""),
                trade.get("phase_at_entry", ""),
                trade.get("kinematics_at_entry", ""),
            ),
        )
        await self._pool.commit()

    async def update_trade_settlement(self, ticket_id: str, settlement: dict) -> None:
        """Patch 3 backfill: overwrite a trade row with broker-truth settlement.

        Fields overwritten from the closing deal (see core.settlement.deal_to_settlement):
        exit_price, commission, swap, gross_pnl, net_pnl, close_reason, exit_time.
        Idempotent: re-running with the same broker deal yields identical rows.
        """
        await self._pool.execute(
            """UPDATE trades
               SET exit_price = ?, commission = ?, swap = ?,
                   gross_pnl = ?, net_pnl = ?, close_reason = ?, exit_time = ?
               WHERE ticket_id = ?""",
            (
                settlement.get("exit_price", 0.0),
                settlement.get("commission", 0.0),
                settlement.get("swap", 0.0),
                settlement.get("gross_pnl", 0.0),
                settlement.get("net_pnl", 0.0),
                settlement.get("close_reason", "BROKER_CLOSED"),
                settlement.get("exit_time", 0),
                ticket_id,
            ),
        )

    async def get_trades(self, symbol: str = "XAUUSDm", limit: int = 50) -> list:
        """Get closed trades for analysis."""
        cursor = await self._pool.execute(
            """SELECT * FROM trades WHERE symbol = ?
               ORDER BY exit_time DESC LIMIT ?""",
            (symbol, limit)
        )
        return await cursor.fetchall()

    async def get_trades_since(self, cutoff_ts: int, limit: int = 1000) -> list:
        """Get closed trades with exit_time >= cutoff as dicts (for trade auditor)."""
        cursor = await self._pool.execute(
            """SELECT ticket_id, symbol, side, lot, entry_price, exit_price,
                      commission, swap, gross_pnl, net_pnl,
                      entry_time, exit_time, close_reason
               FROM trades WHERE exit_time >= ? OR exit_time IS NULL
               ORDER BY exit_time DESC LIMIT ?""",
            (cutoff_ts, limit)
        )
        rows = await cursor.fetchall()
        return [
            {
                "ticket_id": r[0], "symbol": r[1], "side": r[2], "lot": r[3],
                "entry_price": r[4], "exit_price": r[5],
                "commission": r[6], "swap": r[7],
                "gross_pnl": r[8], "net_pnl": r[9],
                "entry_time": r[10], "exit_time": r[11],
                "close_reason": r[12],
            }
            for r in rows
        ]

    async def get_last_trade_timestamp(self) -> Optional[int]:
        """Bootstrap anchor (09-24 D5): MAX(exit_time) of settled trades.
        Returns None when no closed trades exist — caller falls back to N days.
        Used by engine bootstrap to fetch broker deals only since the last
        locally-settled trade (idempotent, incremental on each restart)."""
        cursor = await self._pool.execute(
            "SELECT MAX(exit_time) FROM trades WHERE exit_time IS NOT NULL AND exit_time > 0"
        )
        row = await cursor.fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])

    async def get_daily_pnl(self, symbol: str = "XAUUSDm") -> float:
        """Get today's total net PnL."""
        today_start = int(
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        cursor = await self._pool.execute(
            "SELECT COALESCE(SUM(net_pnl), 0) FROM trades WHERE symbol = ? AND exit_time >= ?",
            (symbol, today_start)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_audit_summary(self, cutoff_ts: int, symbol: str = "XAUUSDm") -> dict:
        """Audit summary: win/loss, total PnL, avg MFE/MAE from pre-computed columns."""
        cursor = await self._pool.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                   SUM(net_pnl) AS total_pnl,
                   AVG(max_favorable_excursion) AS avg_mfe,
                   AVG(max_adverse_excursion) AS avg_mae
               FROM trades
               WHERE symbol = ? AND exit_time >= ?""",
            (symbol, cutoff_ts)
        )
        row = await cursor.fetchone()
        if not row:
            return {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0.0,
                    "avg_mfe": 0.0, "avg_mae": 0.0}
        avg_mfe = row[4] or 0.0
        avg_mae = row[5] or 0.0
        return {
            "total": row[0], "wins": row[1], "losses": row[2],
            "total_pnl": row[3], "avg_mfe": avg_mfe, "avg_mae": avg_mae,
            "mfe_mae_ratio": (avg_mfe / avg_mae) if avg_mae and avg_mae > 0 else 0.0,
        }

    async def get_sl_burn_candidates(self, cutoff_ts: int, symbol: str = "XAUUSDm",
                                     limit: int = 10) -> list:
        """List trades where MAE burned through SL distance (ratio = MAE / |SL-entry|)."""
        cursor = await self._pool.execute(
            """SELECT ticket_id, side, net_pnl,
                      max_adverse_excursion,
                      ABS(stop_loss - entry_price) AS sl_distance,
                      max_adverse_excursion / NULLIF(ABS(stop_loss - entry_price), 0)
                          AS sl_burn_ratio
               FROM trades
               WHERE symbol = ? AND exit_time >= ?
                 AND close_reason != 'TP_HIT'
               ORDER BY sl_burn_ratio DESC LIMIT ?""",
            (symbol, cutoff_ts, limit)
        )
        rows = await cursor.fetchall()
        return [
            {
                "ticket_id": r[0], "side": r[1], "net_pnl": r[2],
                "max_adverse_excursion": r[3], "sl_distance": r[4],
                "sl_burn_ratio": r[5],
            }
            for r in rows
        ]

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("[STORAGE] SQLite connection closed")


_storage_instance: Optional[SQLiteStorage] = None


async def get_storage(db_path: str = "data/scalp5.db") -> SQLiteStorage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = SQLiteStorage(db_path)
        await _storage_instance.initialize()
    return _storage_instance


async def close_storage():
    global _storage_instance
    if _storage_instance:
        await _storage_instance.close()
        _storage_instance = None