import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable, Any
from collections import deque

from metaapi_cloud_sdk.clients.metaapi.synchronization_listener import SynchronizationListener

from src.models import Tick, Candle, Timeframe, SymbolInfo
from src.storage import SQLiteStorage, get_storage
from src.metaapi_client import MetaAPIClient
from src.config import TICK_BUFFER_MAX, TIMESTAMP_MS_THRESHOLD, MILLISECONDS_PER_SECOND

logger = logging.getLogger(__name__)


class _DataRateLimiter:
    """[ANTI-SPAM] Token-bucket rate limiter for MetaAPI historical data requests.

    - Semaphore: max `max_concurrent` simultaneous API calls
    - Token bucket: `rpm` requests/minute, burst `burst` tokens
    - Lazy initialization: Semaphore/Lock created on first acquire() call
      (avoids Python 3.9 'no current event loop' in sync test contexts).

    Usage:
        limiter = _DataRateLimiter(max_concurrent=2, rpm=15, burst=2)
        await limiter.acquire()
        try:
            result = await api_call()
        finally:
            limiter.release()
    """
    def __init__(self, max_concurrent: int = 2, rpm: int = 15, burst: int = 2):
        self._max_concurrent = max_concurrent
        self._rpm = rpm
        self._burst = burst
        self._tokens = float(burst)
        self._max_tokens = float(burst)
        self._refill_rate = rpm / 60.0
        self._last_refill = 0.0
        self._total_calls = 0
        self._total_waited = 0.0
        self._start_time = 0.0
        # Lazy: created on first acquire() inside a running event loop
        # (avoids Python 3.9 get_event_loop() RuntimeError in sync tests)
        self._sem: Optional[asyncio.Semaphore] = None
        self._lock: Optional[asyncio.Lock] = None

    def _ensure_async_primitives(self):
        """Create Semaphore + Lock lazily (must be called inside a running loop)."""
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max_concurrent)
            self._lock = asyncio.Lock()

    async def acquire(self):
        self._ensure_async_primitives()
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            if self._last_refill == 0.0:
                self._last_refill = now
                self._start_time = now
            elapsed = now - self._last_refill
            self._tokens = min(self._max_tokens,
                               self._tokens + elapsed * self._refill_rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._total_calls += 1
                self._log_stats()
                return
            wait = (1.0 - self._tokens) / self._refill_rate
            self._total_waited += wait
            self._tokens = 0.0
            self._last_refill = now + wait
        await asyncio.sleep(wait)
        self._total_calls += 1
        self._log_stats()

    def release(self):
        if self._sem:
            self._sem.release()

    def _log_stats(self):
        if self._total_calls > 0 and self._total_calls % 10 == 0:
            elapsed_min = (time.monotonic() - self._start_time) / 60.0
            actual_rpm = self._total_calls / max(elapsed_min, 0.01)
            logger.info(
                f"[RATE-LIMITER] {self._total_calls} calls | "
                f"{actual_rpm:.1f} RPM | throttled {self._total_waited:.1f}s total"
            )


class TickCollector(SynchronizationListener):
    def __init__(
        self,
        metaapi: MetaAPIClient,
        symbols: List[str],
        storage: Optional[SQLiteStorage] = None,
        on_tick_callback: Optional[Callable[[Tick], Any]] = None,
        on_candle_update: Optional[Callable[[Candle], Any]] = None,
        on_positions_change: Optional[Callable[[str, Any], Any]] = None,
        batch_size: int = 50,  # P0-2: flush at 50 ticks
        batch_interval: float = 0.1,  # P0-2: flush every 100ms
        max_buffer_size: int = TICK_BUFFER_MAX  # P0-2: bounded buffer
    ):
        self.metaapi = metaapi
        self.symbols = symbols
        self.storage = storage
        self.on_tick_callback = on_tick_callback
        self.on_candle_update = on_candle_update
        self.on_positions_change = on_positions_change
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.max_buffer_size = max_buffer_size
        
        self._tick_buffers: Dict[str, deque] = {s: deque(maxlen=max_buffer_size) for s in symbols}
        self._candle_builders: Dict[str, Dict[Timeframe, Dict]] = {s: {} for s in symbols}
        self._last_tick_time: Dict[str, float] = {s: 0.0 for s in symbols}
        self._start_time: float = 0.0
        self._boot_minute = None  # datetime (UTC) — phut chua luc start, candle dau tien partial
        self._running = False
        self._batch_task: Optional[asyncio.Task] = None
        self._stats = {s: {'ticks': 0, 'candles': 0, 'errors': 0, 'buffer_overflows': 0} for s in symbols}
        
        # P0-4: Versioned candle cascade (lock-free)
        self._candle_versions: Dict[str, int] = {s: 0 for s in symbols}
        self._candle_snapshots: Dict[str, Dict] = {s: {} for s in symbols}  # version -> {tf: candle}

        # Streaming position cache (push-driven, event source for orchestrator)
        self._position_cache: Dict[str, Any] = {}
        self._positions_initialized = False
        
        # Stream reconnect with exponential backoff + health monitor
        self._stream_reconnect_lock = asyncio.Lock()
        self._last_stream_reconnect = 0.0
        self._stream_reconnect_min_interval = 5.0
        self._stream_reconnect_max_interval = 60.0
        self._stream_reconnect_base = 5.0
        self._stream_reconnect_attempt = 0
        self._recommended_retry_after = 0.0
        self._stream_monitor_interval = 30.0  # slowed from 10s to reduce concurrent pressure

    async def start(self):
        if not self.metaapi.stream_connection:
            logger.error("[TICK_COLLECTOR] No streaming connection available")
            return
        
        self.metaapi.add_stream_listener(self)
        self._running = True
        self._start_time = time.time()
        self._boot_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self._batch_task = asyncio.create_task(self._flush_loop())
        logger.info(f"[TICK_COLLECTOR] Started for {self.symbols}")

    async def stop(self):
        self._running = False
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        await self._flush_all()
        logger.info(f"[TICK_COLLECTOR] Stopped. Stats: {self._stats}")

    async def on_symbol_price_updated(self, instance_index: str, price: Dict):
        symbol = price.get('symbol')
        if symbol not in self.symbols:
            return
        
        bid = price.get('bid')
        ask = price.get('ask')
        if not bid:
            return
        
        tick_time = price.get('time')
        if isinstance(tick_time, str):
            timestamp = datetime.fromisoformat(tick_time.replace('Z', '+00:00'))
        elif isinstance(tick_time, (int, float)):
            timestamp = datetime.fromtimestamp(tick_time / MILLISECONDS_PER_SECOND if tick_time > TIMESTAMP_MS_THRESHOLD else tick_time, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
        
        tick = Tick(
            symbol=symbol,
            bid=bid,
            ask=ask,
            timestamp=timestamp,
            volume=price.get('volume', 0),
            spread=ask - bid if ask else 0
        )
        
        self._last_tick_time[symbol] = time.time()
        self._stats[symbol]['ticks'] += 1
        
        # P0-2: Check buffer overflow
        buffer = self._tick_buffers[symbol]
        if len(buffer) >= buffer.maxlen:
            self._stats[symbol]['buffer_overflows'] += 1
            logger.warning(f"[TICK_COLLECTOR] {symbol} buffer overflow, dropping oldest tick")
        
        buffer.append(tick)
        
        # P0-2: Flush if batch size reached
        if len(buffer) >= self.batch_size:
            await self._flush_symbol(symbol)
        
        if self.on_tick_callback:
            try:
                await self.on_tick_callback(tick)
            except Exception as e:
                logger.error(f"[TICK_COLLECTOR] on_tick_callback error: {e}")
                self._stats[symbol]['errors'] += 1
        
        self._update_candle_builders(tick)

    def _update_candle_builders(self, tick: Tick):
        symbol = tick.symbol
        current_time = tick.timestamp
        current_minute = current_time.minute + current_time.hour * 60
        current_hour = current_time.hour
        current_day = current_time.day
        
        if Timeframe.M1 not in self._candle_builders[symbol]:
            self._candle_builders[symbol][Timeframe.M1] = {
                'current': None,
                'last_minute': -1
            }
        
        builder_m1 = self._candle_builders[symbol][Timeframe.M1]
        
        if builder_m1['last_minute'] != current_minute:
            if builder_m1['current'] is not None:
                self._finalize_candle(symbol, Timeframe.M1, builder_m1['current'])
            
            candle_time = current_time.replace(second=0, microsecond=0)
            builder_m1['current'] = {
                'time': candle_time,
                'open': tick.bid,
                'high': tick.bid,
                'low': tick.bid,
                'close': tick.bid,
                'tick_volume': 1,
                'spread': tick.spread,
                # Boot-partial: phut chua luc process start → open/thieu nua
                # dau phut, KHONG du tin dung — REST backfill heal.
                'partial_boot': (self._boot_minute is not None
                                 and candle_time <= self._boot_minute),
            }
            builder_m1['last_minute'] = current_minute
        else:
            candle = builder_m1['current']
            if candle:
                candle['high'] = max(candle['high'], tick.bid)
                candle['low'] = min(candle['low'], tick.bid)
                candle['close'] = tick.bid
                candle['tick_volume'] += 1
                candle['spread'] = tick.spread

    def _finalize_candle(self, symbol: str, timeframe: Timeframe, candle_data: Dict):
        candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=candle_data['time'],
            open=candle_data['open'],
            high=candle_data['high'],
            low=candle_data['low'],
            close=candle_data['close'],
            tick_volume=candle_data['tick_volume'],
            spread=candle_data['spread']
        )

        if candle_data.get('partial_boot'):
            # P7-ING (09-10): candle phut boot thieu phan truoc restart —
            # ghi DB de up over REST row dung (INSERT OR REPLACE) va lan vao
            # ATR/swing. Bo qua — startup/post-reconnect backfill heal.
            logger.info(
                f"[TICK_COLLECTOR] boot-partial M1 {candle.timestamp:%H:%M} "
                f"skipped (partial pre-restart)")
            return

        if self.storage:
            asyncio.create_task(self.storage.insert_candle(candle))
        
        if self.on_candle_update:
            try:
                asyncio.create_task(self.on_candle_update(candle))
            except Exception as e:
                logger.error(f"[TICK_COLLECTOR] on_candle_update error: {e}")
        
        self._stats[symbol]['candles'] += 1
        
        # P0-4: Versioned cascade - build snapshot, then atomic version bump
        self._aggregate_higher_timeframes(symbol, candle)
        self._commit_candle_snapshot(symbol)

    def _commit_candle_snapshot(self, symbol: str):
        """P0-4: Atomic version bump for lock-free snapshot reads."""
        self._candle_versions[symbol] += 1
        version = self._candle_versions[symbol]
        
        # Build snapshot with latest candles for all timeframes
        snapshot = {}
        if Timeframe.M1 in self._candle_builders[symbol]:
            builder = self._candle_builders[symbol][Timeframe.M1]
            if builder['current']:
                snapshot[Timeframe.M1] = Candle(
                    symbol=symbol, timeframe=Timeframe.M1,
                    timestamp=builder['current']['time'],
                    open=builder['current']['open'], high=builder['current']['high'],
                    low=builder['current']['low'], close=builder['current']['close'],
                    tick_volume=builder['current']['tick_volume'], spread=builder['current']['spread']
                )
        
        # Add completed higher timeframe candles from builders
        for tf in [Timeframe.M5, Timeframe.M15, Timeframe.H1]:
            if tf in self._candle_builders[symbol]:
                builder = self._candle_builders[symbol][tf]
                if builder['buffer']:
                    last = builder['buffer'][-1]
                    snapshot[tf] = Candle(
                        symbol=symbol, timeframe=tf,
                        timestamp=last.timestamp,
                        open=last.open, high=last.high,
                        low=last.low, close=last.close,
                        tick_volume=last.tick_volume, spread=last.spread
                    )
        
        if snapshot:
            self._candle_snapshots[symbol][version] = snapshot
            # Keep only last 10 versions
            if len(self._candle_snapshots[symbol]) > 10:
                oldest = min(self._candle_snapshots[symbol].keys())
                del self._candle_snapshots[symbol][oldest]

    def get_candle_snapshot(self, symbol: str, version: int = None) -> Dict:
        """P0-4: Get versioned candle snapshot (lock-free read)."""
        if version is None:
            version = self._candle_versions[symbol]
        return self._candle_snapshots[symbol].get(version, {})

    def get_latest_version(self, symbol: str) -> int:
        """P0-4: Get latest candle version."""
        return self._candle_versions[symbol]

    def _aggregate_higher_timeframes(self, symbol: str, m1_candle: Candle):
        """P7-ING (09-10): boundary-aligned HTF aggregation.

        Bug cu: buffer cuon, phat sinh 'candle' moi lan M1 dong → sau restart
        tao loat 5m/15m/1h LECH boundary (vd 07:48, 07:51...) — ~1/2 lịch sử
        DB la duplicate truot, donl tinh SL/TP (atr_m15) + swing/nen bi sai.
        Nay: chi emit tai boundary window (minute-of-day % g == g-1) va chi
        khi window du kin (restart giua window → skip, gap-fill heal)."""
        ts = m1_candle.timestamp
        minute_of_day = ts.hour * 60 + ts.minute
        for tf in [Timeframe.M5, Timeframe.M15, Timeframe.H1]:
            g = 5 if tf == Timeframe.M5 else (15 if tf == Timeframe.M15 else 60)
            if tf not in self._candle_builders[symbol]:
                self._candle_builders[symbol][tf] = {
                    'buffer': [], 'group_size': g
                }
            builder = self._candle_builders[symbol][tf]
            window_start = minute_of_day - (minute_of_day % g)
            builder['buffer'] = [
                c for c in builder['buffer']
                if c.timestamp.hour * 60 + c.timestamp.minute >= window_start
            ]
            builder['buffer'].append(m1_candle)
            if minute_of_day != window_start + g - 1:
                continue  # boundary chua toi
            if len(builder['buffer']) >= g:
                group = builder['buffer'][-g:]
                agg = Candle(
                    symbol=symbol,
                    timeframe=tf,
                    timestamp=group[0].timestamp,
                    open=group[0].open,
                    high=max(c.high for c in group),
                    low=min(c.low for c in group),
                    close=group[-1].close,
                    tick_volume=sum(c.tick_volume for c in group),
                    spread=group[-1].spread
                )

                if self.storage:
                    asyncio.create_task(self.storage.insert_candle(agg))

                if self.on_candle_update:
                    try:
                        asyncio.create_task(self.on_candle_update(agg))
                    except Exception as e:
                        logger.error(f"[TICK_COLLECTOR] on_candle_update error: {e}")

                self._stats[symbol]['candles'] += 1
            else:
                logger.info(
                    f"[TICK_COLLECTOR] {tf.value} window {window_start}m "
                    f"incomplete ({len(builder['buffer'])}/{g}) — skip, "
                    f"backfill heals")
            builder['buffer'] = []

    async def _flush_loop(self):
        while self._running:
            await asyncio.sleep(self.batch_interval)
            await self._flush_all()

    async def _flush_symbol(self, symbol: str):
        """P0-2: Flush ticks for a specific symbol."""
        buffer = self._tick_buffers[symbol]
        if not buffer:
            return
        ticks = list(buffer)
        buffer.clear()
        if self.storage:
            try:
                await self.storage.insert_ticks_batch(ticks)
            except Exception as e:
                logger.error(f"[TICK_COLLECTOR] Batch insert failed for {symbol}: {e}")
                self._stats[symbol]['errors'] += 1

    async def _flush_all(self):
        for symbol in self.symbols:
            await self._flush_symbol(symbol)

    def get_stats(self) -> Dict:
        return self._stats.copy()

    def get_last_tick_age(self, symbol: str) -> float:
        if self._last_tick_time[symbol] == 0:
            # No tick yet — baseline = collector start, NOT inf (prevents
            # watchdog reconnect storm right after (re)connect).
            if self._start_time == 0:
                return float('inf')
            return time.time() - self._start_time
        return time.time() - self._last_tick_time[symbol]

    def get_current_m1_candle(self, symbol: str) -> Optional[Candle]:
        if Timeframe.M1 in self._candle_builders[symbol]:
            builder = self._candle_builders[symbol][Timeframe.M1]
            if builder['current']:
                return Candle(
                    symbol=symbol,
                    timeframe=Timeframe.M1,
                    timestamp=builder['current']['time'],
                    open=builder['current']['open'],
                    high=builder['current']['high'],
                    low=builder['current']['low'],
                    close=builder['current']['close'],
                    tick_volume=builder['current']['tick_volume'],
                    spread=builder['current']['spread']
                )
        return None

    async def on_account_information_updated(self, instance_index, info):
        pass

    async def on_positions_replaced(self, instance_index, positions):
        self._position_cache = {
            self._pos_id(p): p for p in (positions or []) if self._pos_id(p)
        }
        self._positions_initialized = True
        logger.info(
            "[TICK_COLLECTOR] Positions replaced: %d open",
            len(self._position_cache),
        )
        await self._notify_positions_change("replaced", positions or [])

    async def on_position_updated(self, instance_index, position):
        pid = self._pos_id(position)
        if pid:
            self._position_cache[pid] = position
        self._positions_initialized = True
        await self._notify_positions_change("updated", position)

    async def on_position_removed(self, instance_index, position_id):
        pid = str(position_id) if position_id is not None else None
        if pid:
            self._position_cache.pop(pid, None)
        self._positions_initialized = True
        await self._notify_positions_change("removed", pid)

    async def _notify_positions_change(self, event: str, payload: Any):
        if not self.on_positions_change:
            return
        try:
            await self.on_positions_change(event, payload)
        except Exception as e:
            logger.error(f"[TICK_COLLECTOR] on_positions_change error: {e}")

    @staticmethod
    def _pos_id(position) -> Optional[str]:
        """Extract broker position id from dict or SDK object."""
        if position is None:
            return None
        if isinstance(position, dict):
            return str(position.get("id") or "")
        return str(getattr(position, "id", None) or "")

    def get_position_cache(self) -> List[Any]:
        """Event-driven position cache (push updates, free)."""
        return list(self._position_cache.values())

    def is_positions_initialized(self) -> bool:
        return self._positions_initialized

    async def on_pending_orders_replaced(self, instance_index, orders):
        pass

    async def on_pending_order_updated(self, instance_index, order):
        pass


class HistoricalDataFetcher:
    """[ANTI-SPAM] Rate-limited historical data fetcher for MetaAPI.

    Uses _DataRateLimiter (15 RPM, burst 2, max 2 concurrent) to prevent
    Exness/MT5 rate-limiting. All historical candle calls go through
    this limiter — no unbounded request bursts.
    """
    def __init__(self, metaapi: MetaAPIClient, storage: SQLiteStorage):
        self.metaapi = metaapi
        self.storage = storage
        self._rate_limiter = _DataRateLimiter(max_concurrent=2, rpm=15, burst=2)
        self._last_fetch: Dict[str, Dict[Timeframe, float]] = {}
        self._min_fetch_interval = 2.0  # 2s between API calls (was 1s — anti-spam)

    # [ANTI-SPAM] Default limits: 5 sequential calls, total 2500 candles.
    # D1:200 (200d) · H1:500 (20.8d) · M15:500 (5.2d) · M5:500 (41.7h) · M1:800 (13.3h)
    _DEFAULT_LIMITS: Dict[Timeframe, int] = {
        Timeframe.M1: 800,
        Timeframe.M5: 500,
        Timeframe.M15: 500,
        Timeframe.H1: 500,
        Timeframe.D1: 200,
    }

    async def fetch_all_timeframes(
        self,
        symbol: str,
        timeframes: List[Timeframe] = None,
        limits: Dict[Timeframe, int] = None
    ) -> Dict[Timeframe, List[Candle]]:
        """[ANTI-SPAM] Sequential D1→H1→M15→M5→M1, staggered 2s per TF.

        Macro context (D1/H1) fetched first — most stable, lowest rate-limit risk.
        M1 last — highest frequency, most candles. No asyncio.gather.
        """
        if timeframes is None:
            # D1 first: fetch macro context before micro
            timeframes = [Timeframe.D1, Timeframe.H1,
                          Timeframe.M15, Timeframe.M5, Timeframe.M1]
        if limits is None:
            limits = self._DEFAULT_LIMITS

        results: Dict[Timeframe, List[Candle]] = {}
        for tf in timeframes:
            limit = limits.get(tf, 100)
            candles = await self._fetch_with_limit(symbol, tf, limit)
            if candles:
                await self.storage.insert_candles_batch(candles)
                logger.info(f"[FETCHER] {symbol} {tf.value}: fetched {len(candles)} candles (limit={limit})")
            results[tf] = candles
            await asyncio.sleep(2.0)  # 2s stagger between TFs (anti-spam)
        return results

    async def _fetch_with_limit(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int,
        start_time: Optional[datetime] = None
    ) -> List[Candle]:
        """Rate-limited MetaAPI call. Holds limiter for entire call duration."""
        await self._rate_limiter.acquire()
        try:
            await asyncio.sleep(self._min_fetch_interval)
            return await self.metaapi.fetch_candles(symbol, timeframe, limit, start_time=start_time)
        finally:
            self._rate_limiter.release()

    async def fetch_latest(self, symbol: str, timeframe: Timeframe, limit: int = 800) -> List[Candle]:
        """Fetch latest candles with rate limiting.

        Default limit=800 matches M1 warmup. D1/H1/M15/M5 callers
        pass explicit limits (see _DEFAULT_LIMITS in engine._gap_fill_sequential).
        """
        return await self._fetch_with_limit(symbol, timeframe, limit)

    async def backfill_gaps(
        self,
        symbol: str,
        timeframe: Timeframe,
        max_gap_minutes: int = 60
    ) -> int:
        # Storage read outside rate limiter (no API call)
        candles = await self.storage.get_candles(symbol, timeframe, limit=2)
        if len(candles) < 2:
            return 0

        expected_interval = self._get_interval_minutes(timeframe)
        actual_gap = (candles[-1].timestamp - candles[-2].timestamp).total_seconds() / 60

        if actual_gap > expected_interval * 1.5 and actual_gap <= max_gap_minutes:
            missing = int(actual_gap / expected_interval) - 1
            if missing > 0:
                # Rate-limited API call (capped at 1000 candles/request)
                new_candles = await self._fetch_with_limit(
                    symbol, timeframe, limit=min(missing + 2, 1000)
                )
                if new_candles:
                    await self.storage.insert_candles_batch(new_candles)
                    logger.info(f"[FETCHER] Backfilled {len(new_candles)} {timeframe.value} candles for {symbol}")
                    return len(new_candles)
        return 0

    # [ANTI-SPAM 2026-09-22] Max age (days) of a gap's NEWER boundary worth
    # fetching. Stale gaps (> cap) have no live-trading value and old weekend
    # gaps always return 0 candles — pure spam on No-Redundancy accounts.
    _MAX_GAP_AGE_DAYS = {
        Timeframe.M1: 3,
        Timeframe.M5: 7,
        Timeframe.M15: 14,
        Timeframe.H1: 30,
        Timeframe.D1: 90,
    }
    _DEFAULT_MAX_GAP_AGE_DAYS = 14

    @classmethod
    def _age_ok(cls, ts: datetime, max_age_days: Optional[int]) -> bool:
        """True if ts is within the age cap (newer boundary of the gap)."""
        if max_age_days is None:
            return True
        now = datetime.now(timezone.utc)
        return (now - ts).total_seconds() <= max_age_days * 86400.0

    async def backfill_all_gaps(
        self,
        symbol: str,
        timeframe: Timeframe,
        chunk_size: int = 1000,  # Max MetaAPI limit: 1000 candles/request
        max_gap_minutes: int = 240,
        max_gap_age_days: Optional[int] = None
    ) -> int:
        """FILL-ALL-GAPS: scan the ENTIRE stored series for missing candles and
        fetch every gap — WITH max_gap_minutes cap to prevent massive historical fetch.

        Loads the full candle history (paginated, oldest→newest), walks it to
        detect every break > 1.5× expected interval, then rate-limited chunked
        REST fetches walking BACKWARD from the gap's upper bound (MetaAPI
        loads candles in backward direction: start_time is the LATEST time,
        limit ≤ 1000 per request) until the gap is closed or the broker
        returns nothing inside the window (weekend/holiday close — skip).

        Idempotent: INSERT OR REPLACE on UNIQUE(symbol,timeframe,timestamp).
        Runs in background gap-fill — never in the 1Hz loop.
        
        Args:
            max_gap_minutes: Budget for gaps larger than this (default 240m = 4h).
                           For a larger gap, only the NEWEST max_candles are
                           fetched (max_candles = max_gap_minutes / interval),
                           not the entire historical block.
            max_gap_age_days: [ANTI-SPAM 2026-09-22] Skip gaps whose newer
                           boundary is older than this (per-TF default).
                           Stale gaps are never worth a broker call.
        """
        expected_interval = self._get_interval_minutes(timeframe)
        if expected_interval <= 0:
            return 0

        # [ANTI-SPAM] resolve age cap (per-TF default if not explicit)
        if max_gap_age_days is None:
            max_gap_age_days = self._MAX_GAP_AGE_DAYS.get(timeframe, self._DEFAULT_MAX_GAP_AGE_DAYS)

        # 1. Load full series oldest→newest (get_candles returns reversed rows).
        series: List[Candle] = []
        before: Optional[datetime] = None
        while True:
            page = await self.storage.get_candles(symbol, timeframe, limit=1000, before=before)
            if not page:
                break
            series = page + series  # page is already oldest→newest
            before = page[0].timestamp
            if len(page) < 1000:
                break
        if len(series) < 2:
            return 0

        # 2. Walk series, detect gaps, fetch each missing block in chunks.
        total_filled = 0
        fetch_calls = 0  # [ANTI-SPAM] per-run cap: never hammer the broker
        max_fetch_calls = 30
        # [KNOWN-EMPTY-GAP F2, 2026-09-22] gaps the broker already answered
        # "0 candles" for (session-close/rollover) — skip with 0 API calls.
        resolved_gaps = await self.storage.get_resolved_gaps(symbol, timeframe)
        for i in range(1, len(series)):
            prev_c, cur_c = series[i - 1], series[i]
            gap_min = (cur_c.timestamp - prev_c.timestamp).total_seconds() / 60.0
            if gap_min <= expected_interval * 1.5:
                continue  # contiguous (weekend-clean series)
            missing = int(gap_min / expected_interval) - 1
            if missing <= 0:
                continue

            # [KNOWN-EMPTY-GAP F2] broker returned 0 for this exact window
            # before (settled session/rollover gap) — no data can appear
            # inside it, so skip without any API call.
            if (prev_c.timestamp, cur_c.timestamp) in resolved_gaps:
                logger.info(
                    f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                    f"SKIP known-empty gap {prev_c.timestamp} → "
                    f"{cur_c.timestamp} ({gap_min:.0f}m) — 0 API calls")
                continue

            # [ANTI-SPAM 2026-09-22, user directive] Gaps larger than
            # max_gap_minutes: don't pull the entire massive historical block.
            # Fetch only the NEWEST max_candles (the recent tail live trading
            # needs); the older portion stays deferred. The chunk loop below
            # fetches backward from the newest, so capping `missing` stops it
            # after exactly max_candles. max_candles is always < 1000/request
            # for our TFs (M1 800, M5 500, M15 500, H1 500, D1 200) → 1 call.
            max_candles = int(max_gap_minutes / expected_interval)
            if missing > max_candles:
                logger.info(
                    f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                    f"gap {prev_c.timestamp} → {cur_c.timestamp} "
                    f"({gap_min:.0f}m > {max_gap_minutes}m max) — fetch only "
                    f"the newest {max_candles} candles")
                missing = max_candles

            # [ANTI-SPAM 2026-09-22] Age cap: gaps whose NEWER boundary is
            # older than max_gap_age_days are stale history — no live-trading
            # value, and every fetch of an old weekend gap returns 0 candles
            # (~80/TF accumulated → hundreds of wasted calls per startup on a
            # No-Redundancy account). Skip with 0 API calls; recent gaps still
            # fill normally.
            if not self._age_ok(cur_c.timestamp, max_gap_age_days):
                logger.info(
                    f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                    f"SKIP stale gap {prev_c.timestamp} → {cur_c.timestamp} "
                    f"(newer boundary > {max_gap_age_days}d old — no live value)")
                continue

            # [ANTI-SPAM] per-run cap — remaining gaps defer to next startup
            # (gaps persist in the series; fetches are idempotent).
            if fetch_calls >= max_fetch_calls:
                logger.warning(
                    f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                    f"per-run cap {max_fetch_calls} reached — deferring remaining gaps")
                break

            logger.info(
                f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                f"gap {prev_c.timestamp} → {cur_c.timestamp} "
                f"({gap_min:.0f}m, ~{missing} missing)")
            filled_here = 0
            # Fetch backward from the newest missing candle (upper bound).
            upper = cur_c.timestamp - timedelta(minutes=expected_interval)
            while filled_here < missing and upper > prev_c.timestamp:
                if fetch_calls >= max_fetch_calls:
                    break  # per-run cap — defer remainder to next startup
                need = min(chunk_size, missing - filled_here)
                # +1 for boundary candle; cap at 1000 (MetaAPI max/request)
                fetch_limit = min(need + 1, 1000)
                fetch_calls += 1
                new_candles = await self._fetch_with_limit(
                    symbol, timeframe, fetch_limit, start_time=upper)
                if not new_candles:
                    break  # broker has no data for this window (weekend/holiday)
                # Count only candles strictly inside the gap window; the +1
                # extra may include the already-stored boundary candle cur_c.
                gap_new = [c for c in new_candles
                           if prev_c.timestamp < c.timestamp < cur_c.timestamp]
                if not gap_new:
                    break  # nothing new inside the gap → stop this gap
                # INSERT OR REPLACE is idempotent for any overlap.
                await self.storage.insert_candles_batch(new_candles)
                actual = min(len(gap_new), missing - filled_here)
                filled_here += actual
                total_filled += actual
                oldest_ts = min(c.timestamp for c in new_candles)
                upper = oldest_ts - timedelta(minutes=expected_interval)
                await asyncio.sleep(2.0)  # [ANTI-SPAM] 2s between chunk fetches
            logger.info(f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: filled {filled_here} candles")
            # [KNOWN-EMPTY-GAP F2] broker answered 0 for this settled window
            # (session-close/rollover) — remember it so the next startup
            # skips it with 0 API calls. Only mark gaps we actually attempted
            # to fetch (deferred/per-run-capped gaps stay unmarked).
            if filled_here == 0:
                await self.storage.mark_gap_resolved(
                    symbol, timeframe, prev_c.timestamp, cur_c.timestamp)

        # [TAIL-GAP HEAL F1, 2026-09-22] The walk above only covers INTERNAL
        # holes between stored candles. If the bot was down (BLIND / stopped /
        # designed-restart) for >1 interval, the tail [last_stored → now] is
        # missing and was never backfilled (assumed covered by live ticks —
        # false after a long outage: on 09-22 5m/15m went 2h+ stale). Heal
        # it with the broker's newest candles, chunked backward like
        # internal gaps; INSERT OR REPLACE dedupes any overlap.
        if fetch_calls < max_fetch_calls:
            last_ts = series[-1].timestamp
            now_ts = datetime.now(timezone.utc)
            tail_min = (now_ts - last_ts).total_seconds() / 60.0
            # [G4 2026-09-22] a STALE tail (oldest stored boundary older than
            # the per-TF age cap) is skipped exactly like stale internal gaps —
            # an 18-month-old D1 tail has no live-trading value.
            tail_age_ok = (max_gap_age_days is None
                           or self._age_ok(last_ts, max_gap_age_days))
            if tail_min > expected_interval * 1.5 and tail_age_ok:
                tail_missing = int(tail_min / expected_interval)
                upper = now_ts
                filled_here = 0
                while filled_here < tail_missing and upper > last_ts:
                    if fetch_calls >= max_fetch_calls:
                        break
                    need = min(chunk_size, tail_missing - filled_here)
                    fetch_limit = min(need + 1, 1000)
                    fetch_calls += 1
                    tail_candles = await self._fetch_with_limit(
                        symbol, timeframe, fetch_limit, start_time=upper)
                    if not tail_candles:
                        break  # market closed — nothing newer
                    tail_new = [c for c in tail_candles if c.timestamp > last_ts]
                    if not tail_new:
                        break  # broker's newest ≤ last stored → tail complete
                    await self.storage.insert_candles_batch(tail_new)
                    filled_here += len(tail_new)
                    total_filled += len(tail_new)
                    # -1 interval like the internal-gap loop: next fetch starts
                    # strictly BEFORE this chunk's oldest → no overlap double-count.
                    upper = min(c.timestamp for c in tail_new) - timedelta(minutes=expected_interval)
                    await asyncio.sleep(2.0)  # [ANTI-SPAM] same as internal chunks
                if filled_here:
                    logger.info(
                        f"[FETCHER] ALL-GAPS {symbol} {timeframe.value}: "
                        f"tail gap {last_ts} → {now_ts} ({tail_min:.0f}m) "
                        f"— healed {filled_here} candles")

        if total_filled:
            logger.info(f"[FETCHER] ALL-GAPS total: {total_filled} {timeframe.value} candles filled for {symbol}")
        return total_filled

    async def backfill_since(
        self,
        symbol: str,
        timeframe: Timeframe,
        since_ts: datetime,
        max_gap_minutes: int = 120
    ) -> int:
        """SP-2: Backfill candles from since_ts to now via rate-limited REST.

        MetaAPI loads candles in BACKWARD direction (start_time = latest time),
        so we fetch the newest `needed` candles (no start_time) — the missing
        post-reconnect window is always at the tail of the series.
        Skips gaps > max_gap_minutes (avoid fetching massive blocks).
        Idempotent: UNIQUE(symbol, timeframe, timestamp) + INSERT OR REPLACE.
        """
        now_ts = datetime.now(timezone.utc)
        gap_minutes = (now_ts - since_ts).total_seconds() / 60
        if gap_minutes <= 0:
            return 0
        if gap_minutes > max_gap_minutes:
            logger.warning(
                f"[FETCHER] Gap {gap_minutes:.0f}m > {max_gap_minutes}m for {symbol} "
                f"{timeframe.value} - skipping backfill")
            return 0

        interval = self._get_interval_minutes(timeframe)
        needed = int(gap_minutes / interval) + 2
        needed = min(needed, 2000)  # safety cap
        candles = await self._fetch_with_limit(symbol, timeframe, needed)
        if candles:
            await self.storage.insert_candles_batch(candles)
            logger.info(f"[FETCHER] Backfilled {len(candles)} {timeframe.value} candles for {symbol}")
            return len(candles)
        return 0

    def _get_interval_minutes(self, timeframe: Timeframe) -> int:
        mapping = {
            Timeframe.M1: 1,
            Timeframe.M5: 5,
            Timeframe.M15: 15,
            Timeframe.H1: 60,
            Timeframe.H4: 240,
            Timeframe.D1: 1440
        }
        return mapping.get(timeframe, 1)