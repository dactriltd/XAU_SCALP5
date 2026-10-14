import asyncio
import logging
import os
import random
import ssl
import time
import traceback
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from metaapi_cloud_sdk import MetaApi
from metaapi_cloud_sdk.clients.metaapi.metaapi_websocket_client import MetaApiWebsocketClient
from metaapi_cloud_sdk.clients.metaapi.metatrader_account_client import MetatraderAccountClient
from metaapi_cloud_sdk.clients.error_handler import TooManyRequestsException  # 429 rate-limit (docs: rateLimiting)
from metaapi_cloud_sdk.clients.metaapi.synchronization_listener import SynchronizationListener

from src.config import TIMESTAMP_MS_THRESHOLD, MILLISECONDS_PER_SECOND

# Proxy support
_HTTP_PROXY = os.environ.get('HTTP_PROXY')
_HTTPS_PROXY = os.environ.get('HTTPS_PROXY')
if _HTTPS_PROXY:
    _PROXY_URL = _HTTPS_PROXY
elif _HTTP_PROXY:
    _PROXY_URL = _HTTP_PROXY
else:
    _PROXY_URL = None

# Mac-specific SSL context
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = True
_SSL_CONTEXT.verify_mode = ssl.CERT_REQUIRED

from src.models import (
    Candle, AccountInfo, SymbolInfo, Timeframe, ConnectionState
)
from src.storage import SQLiteStorage, get_storage

logger = logging.getLogger(__name__)


# Callbacks the MetaAPI websocket client invokes on EVERY registered
# synchronization listener. A duck-typed listener (plain callable, partial
# object) missing these used to raise AttributeError on each broker-status /
# health event — see fix 2026-09-15.
_CORE_LISTENER_METHODS = (
    'on_broker_connection_status_changed',
    'on_health_status',
    'on_connected',
    'on_disconnected',
    'on_symbol_price_updated',
)


class _SafeSynchronizationListener:
    """Adapter around a partially-implemented synchronization listener.

    MetaAPI's websocket client calls every SynchronizationListener callback
    (e.g. ``on_broker_connection_status_changed``, ``on_health_status``) on all
    registered listeners. Listeners that only implement a subset of the
    interface (or are bare callables, as registered by older diagnostic code)
    crashed with AttributeError on each such event. This adapter delegates any
    callback the wrapped listener DOES implement and no-ops the rest, so
    registration can never break the SDK event loop."""

    def __init__(self, listener):
        self.__dict__['_listener'] = listener

    @property
    def wrapped(self):
        return self.__dict__['_listener']

    def __getattr__(self, name):
        attr = getattr(self.__dict__['_listener'], name, None)
        if callable(attr):
            async def _delegate(*args, **kwargs):
                result = attr(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            return _delegate

        async def _noop(*args, **kwargs):
            pass
        return _noop


class MetaAPIClient:
    def __init__(
        self,
        token: str,
        account_id: str,
        storage: Optional[SQLiteStorage] = None
    ):
        self.token = token
        self.account_id = account_id
        self.storage = storage
        
        # DO NOT set domain explicitly - let MetaAPI SDK auto-route based on account region
        # Per MetaAPI docs: "Please make sure you do not pass region option to MetaApi constructor for javascript and python SDKs"
        self._domain = None
        
        self.api: Optional[MetaApi] = None
        self.account: Optional[MetatraderAccountClient] = None
        self.rpc_connection = None
        self.stream_connection = None
        self._market_watch_symbols: set = set()  # MARKET-WATCH-FIRST-SEQ: subscribed symbols
        
        self._state = ConnectionState()
        self._deploy_timeout = 300.0            # Increased from 60s to 300s (5 min) for slow deployments
        self._connect_timeout = 60.0
        self._sync_timeout = 180.0
        # RPC trading-channel self-heal (fix 2026-09-11): a closed rpc_connection
        # made every market order fail "connection has been closed" until restart.
        self._rpc_reconnect_lock = asyncio.Lock()
        self._rpc_seq = 0
        self._last_rpc_reconnect = 0.0
        self._rpc_reconnect_min_interval = 2.0
        
        # Streaming WebSocket self-heal: monitor + auto-reconnect
        self._stream_reconnect_lock = asyncio.Lock()
        self._stream_seq = 0
        self._last_stream_reconnect = 0.0
        self._stream_reconnect_min_interval = 5.0
        self._stream_monitor_task: Optional[asyncio.Task] = None
        self._stream_monitor_interval = 10.0  # check every 10s
        self._stream_symbols: List[str] = []
        # 13-10 tối 21:xx — stuck-sync recovery (MetaApi docs): listeners là per-connection
        # (SDK) → registry để re-attach khi swap streaming connection (không re-attach =
        # tick feed chết thầm = 'stream chết im lặng' định kỳ); escalation flag chống redeploy storm
        self._stream_listeners: List = []
        self._stuck_sync_escalated: bool = False

        # STALL DIAGNOSTICS (gated by STALL_DIAG_LOGS flag — zero output when OFF)
        self._stall_diag_logs_flag: bool = os.getenv("STALL_DIAG_LOGS", "false").lower() == "true"
        self._last_chunk_ts: Dict[str, float] = {}  # symbol -> last tick arrival ts (WS_CHUNK_GAP)
        self._ws_connect_ts: Optional[float] = None  # WS connect event timestamp (WS_LIFECYCLE)
        self._ws_disconnect_ts: Optional[float] = None  # WS disconnect event timestamp (WS_LIFECYCLE)
        self._subscribe_seq: List[Dict[str, Any]] = []  # subscription sequence events (SUB_SEQUENCE)
        self._terminal_status_ts: float = 0.0  # last terminal status sample ~every 60s (TERMINAL_STATUS)

        # Streaming sync + broker-readiness (fix 2026-09-15): "account is not
        # connected to broker yet" surfaced as silent sync timeouts and
        # subscription failures — make readiness an explicit, retried gate.
        self._stream_sync_timeout = 180.0
        self._stream_sync_max_retries = 5       # 5 retries (1 initial + 5 = 6 attempts)
        self._stream_sync_backoff_step = 10.0   # sleeps 10s, 20s, 30s, 40s, 50s
        # USER 14/10 (ORDER BOOT + anti-rate-limit): throttle tuần tự giữa các RPC lịch sử —
        # ≥5s giữa 2 lần gọi + honor 429 recommendedRetryTime (docs: "throttle historical data requests").
        self._hist_last_call = 0.0
        self._hist_min_interval = 5.0
        self._broker_ready_timeout = 180.0      # Increased from 60s to 180s for slow broker connections
        self._broker_ready_poll_interval = 5.0  # Increased from 2s to 5s
        self._subscribe_timeout = 30.0          # Increased from 15s to 30s
        self._subscribe_max_attempts = 5        # Increased from 3 to 5

    async def initialize(self) -> bool:
        try:
            # Do NOT pass domain - let MetaAPI SDK auto-route based on account region
            # Per MetaAPI docs: "Please make sure you do not pass region option to MetaApi constructor for javascript and python SDKs"
            self.api = MetaApi(self.token)
            self.account = await asyncio.wait_for(
                self.api.metatrader_account_api.get_account(self.account_id),
                timeout=self._connect_timeout
            )
            
            # Log account region for debugging
            if hasattr(self.account, 'region') and self.account.region:
                logger.info(f"[METAAPI] Account region: {self.account.region}")
            if hasattr(self.account, 'connection_status'):
                logger.info(f"[METAAPI] Account connection_status: {self.account.connection_status}")
            logger.info(f"[METAAPI] Account state: {self.account.state}")

            # Official MetaAPI pattern (fix 2026-09-15): wait_connected() is
            # called UNCONDITIONALLY — it waits until the account is BOTH
            # deployed AND connected to the broker. A DEPLOYED-but-not-yet-
            # broker-connected account (slow deploy, dormant weekend session)
            # previously skipped this gate entirely, so every downstream
            # subscribe failed "account is not connected to broker yet".
            initial_state = self.account.state
            deployed_states = ('DEPLOYING', 'DEPLOYED')
            if initial_state not in deployed_states:
                logger.info(
                    f"[METAAPI] Account state={initial_state!r} — deploying..."
                )
                await self.account.deploy()

            # Fix 2026-09-21: Check connection_status before wait_connected()
            # per official MetaAPI streaming example
            if hasattr(self.account, 'connection_status') and self.account.connection_status != 'CONNECTED':
                logger.info(
                    f"[METAAPI] Account connection_status={self.account.connection_status!r} "
                    f"— waiting for broker connection..."
                )
                await asyncio.wait_for(
                    self.account.wait_connected(),
                    timeout=self._deploy_timeout
                )
                logger.info(
                    f"[METAAPI] Account connected to broker "
                    f"(state={self.account.state!r})"
                )
            elif self.account.state not in deployed_states:
                logger.info(
                    f"[METAAPI] Account state={initial_state!r} — deploying..."
                )
                await self.account.deploy()
                logger.info(
                    "[METAAPI] Waiting for MetaAPI server to connect to broker "
                    f"(may take a couple of minutes, timeout={self._deploy_timeout}s)..."
                )
                await asyncio.wait_for(
                    self.account.wait_connected(),
                    timeout=self._deploy_timeout
                )
                logger.info(
                    f"[METAAPI] Account connected to broker "
                    f"(state={self.account.state!r})"
                )

            logger.info("[METAAPI] Establishing RPC trading connection...")
            self.rpc_connection = self.account.get_rpc_connection()
            await self.rpc_connection.connect()

            # RPC WARMUP (ORDER BOOT 14/10 USER): "RPC warmup hoàn chỉnh" — 3 attempt
            # tuần tự (120s + 120s + 60s = budget 300s) trên kênh RPC, XONG trước khi
            # mở kênh WS (một kênh một lúc, không song song). Terminal down → đốt
            # trọn budget rồi fail-open (is_synchronized=False; guarded calls +
            # backoff loop tự recover sau).
            rpc_synced = False
            for attempt, sync_attempt_timeout in ((1, 120.0), (2, 120.0), (3, 60.0)):
                try:
                    logger.info(
                        f"[METAAPI] RPC warmup attempt {attempt}/3 "
                        f"(timeout={sync_attempt_timeout:.0f}s)..."
                    )
                    await self._rpc_wait_synchronized(self.rpc_connection, sync_attempt_timeout)
                    rpc_synced = True
                    logger.info(f"[METAAPI] RPC warmup complete (attempt {attempt}/3) — terminal synchronized")
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[METAAPI] RPC warmup attempt {attempt}/3 timed out after "
                        f"{sync_attempt_timeout:.0f}s | {self._broker_status_snapshot()}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[METAAPI] RPC warmup attempt {attempt}/3 failed: "
                        f"{type(e).__name__}: {e}"
                    )
            self._state.is_synchronized = rpc_synced
            if not rpc_synced:
                logger.error(
                    "[METAAPI] RPC terminal NOT synchronized after 3 warmup attempts — "
                    "proceeding anyway (fail-open; gap-fill uses the historical data "
                    "channel, not RPC; guarded calls + backoff loop self-heal via _reconnect_rpc)"
                )

            self._state.is_connected = True
            logger.info(
                f"[METAAPI] Connected to account {self.account_id[-4:]} "
                f"(rpc_synchronized={rpc_synced})"
            )
            return True
            
        except Exception as e:
            self._state.last_error = str(e)
            self._state.is_connected = False
            logger.error(f"[METAAPI] Connection failed: {e}")
            return False

    def _streaming_state(self):
        """Local copy of terminal state pushed by WebSocket (free, event-driven)."""
        if not self.stream_connection:
            return None
        return getattr(self.stream_connection, 'terminal_state', None)

    def _account_info_from_dict(self, info: Dict) -> AccountInfo:
        return AccountInfo(
            account_id=self.account_id,
            balance=info.get('balance') or 0,
            equity=info.get('equity') or 0,
            free_margin=info.get('freeMargin') or 0,
            margin_level=info.get('marginLevel') or 0,
            leverage=info.get('leverage') or 1,
            currency=info.get('currency') or 'USD',
            server_time=datetime.fromtimestamp(info.get('serverTime', 0) / MILLISECONDS_PER_SECOND, tz=timezone.utc)
        )

    async def get_account_info(self) -> Optional[AccountInfo]:
        # 1. Prefer streaming terminal_state (free, push-driven — no RPC credits)
        ts = self._streaming_state()
        if ts is not None:
            try:
                info = ts.account_information
                if info:
                    return self._account_info_from_dict(info)
            except Exception as e:
                logger.warning(f"[METAAPI] Streaming account info read failed: {e}")
        # 2. Fallback RPC (only when streaming not synced)
        if not self.rpc_connection:
            return None
        try:
            info = await asyncio.wait_for(
                self.rpc_connection.get_account_information(),
                timeout=self._connect_timeout
            )
            return self._account_info_from_dict(info)
        except Exception as e:
            logger.error(f"[METAAPI] Failed to get account info: {e}")
            return None

    async def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        if not self.rpc_connection:
            return None
        try:
            specs = await self.rpc_connection.get_symbol_specification(symbol)
            if not specs:
                return None
            return SymbolInfo(
                symbol=symbol,
                base_asset=specs.get('currency', symbol[:3]),
                pip_size=specs.get('pipSize', 0.01),
                contract_size=specs.get('contractSize', 100.0),
                min_lot=specs.get('minVolume', 0.01),
                max_lot=specs.get('maxVolume', 100.0),
                lot_step=specs.get('volumeStep', 0.01),
                spread_typical=specs.get('spread', 0),
                commission_per_lot=specs.get('commission', 0),
                margin_currency=specs.get('marginCurrency', 'USD')
            )
        except Exception as e:
            logger.error(f"[METAAPI] Failed to get symbol info for {symbol}: {e}")
            return None

    async def _throttle_historical(self) -> None:
        """USER 14/10 (ORDER BOOT): rate-limit tuần tự giữa các RPC lịch sử.
        MetaApi docs: throttle historical requests; hard cap 5 concurrent/account.
        Mình serialize thêm: ≥ _hist_min_interval (5s) giữa 2 lần gọi,
        bất kể caller (fetch_candles / get_history_deals / gap-filler chunks)."""
        wait = self._hist_min_interval - (time.monotonic() - self._hist_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._hist_last_call = time.monotonic()

    async def _wait_for_429(self, e: Exception, ctx: str) -> None:
        """USER 14/10: honor MetaApi 429 recommendedRetryTime (docs: "wait the recommended
        time as per the error payload"). SDK đã retry nội bộ → đây là outer-wait
        trước lần thử kế tiếp (cap 120s để giữ boot bounded)."""
        wait = 30.0
        meta = getattr(e, "metadata", None)
        if isinstance(meta, dict):
            rrt = meta.get("recommendedRetryTime")
            if rrt:
                try:
                    until = datetime.fromisoformat(str(rrt).replace("Z", "+00:00")).timestamp()
                    wait = max(5.0, min(until - time.time(), 120.0))
                except Exception:
                    pass
        logger.warning(f"[METAAPI] {ctx}: 429 rate-limit → chờ {wait:.0f}s (recommendedRetryTime, cap 120s)")
        await asyncio.sleep(wait)

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 100,
        start_time: Optional[datetime] = None,
        max_retries: int = 3
    ) -> List[Candle]:
        """Fetch historical candles with exponential backoff retry.

        [ANTI-SPAM] Up to `max_retries` retries with 2s → 4s → 8s backoff.
        Rate limiting is handled by HistoricalDataFetcher._DataRateLimiter.
        MetaAPI limit capped at 1000 candles/request.
        """
        if not self.account:
            return []
        limit = min(limit, 1000)  # Enforce MetaAPI cap

        for attempt in range(max_retries + 1):
            await self._throttle_historical()  # USER 14/10: ≥5s giữa 2 lần gọi lịch sử
            try:
                kwargs = {'limit': limit}
                if start_time:
                    kwargs['start_time'] = start_time

                raw_candles = await self.account.get_historical_candles(
                    symbol, timeframe.value, **kwargs
                )

                candles = []
                for c in raw_candles:
                    timestamp = c.get('time')
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    elif isinstance(timestamp, (int, float)):
                        timestamp = datetime.fromtimestamp(timestamp / MILLISECONDS_PER_SECOND if timestamp > TIMESTAMP_MS_THRESHOLD else timestamp, tz=timezone.utc)
                    candles.append(Candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=timestamp,
                        open=c['open'],
                        high=c['high'],
                        low=c['low'],
                        close=c['close'],
                        tick_volume=c.get('tickVolume', 0),
                        spread=c.get('spread', 0)
                    ))
                return candles
            except TooManyRequestsException as e:  # 429: honor recommendedRetryTime (docs)
                if attempt < max_retries:
                    await self._wait_for_429(e, f"fetch_candles {timeframe.value} {symbol}")
                    continue
                logger.error(
                    f"[METAAPI] fetch_candles {timeframe.value} {symbol}: "
                    f"429 rate-limit — hết retry: {str(e)[:100]}"
                )
                return []
            except Exception as e:
                if attempt < max_retries:
                    wait = 2.0 * (2 ** attempt)  # 2s, 4s, 8s
                    logger.warning(
                        f"[METAAPI] fetch_candles {timeframe.value} {symbol}: "
                        f"attempt {attempt+1}/{max_retries+1} failed "
                        f"({str(e)[:80]}), retry in {wait:.0f}s"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"[METAAPI] Failed to fetch {timeframe.value} candles for "
                        f"{symbol} after {max_retries+1} attempts: {e}"
                    )
                    return []
        return []

    async def start_streaming(self, symbols: List[str]) -> bool:
        self._stream_symbols = symbols
        # Chu kỳ startup MỚI = ngân sách escalation MỚI (1 redeploy/chu kỳ,
        # ensure_market_watch phía trên giữ flag hiện tại để không redeploy storm).
        self._stuck_sync_escalated = False
        return await self._start_streaming_internal(symbols, start_monitor=True)

    async def pipeline_check(self, symbols: List[str]) -> bool:
        """ORDER BOOT 14/10 (USER): "kiểm tra đường ống có được thông hay không"
        sau khi mở WS: (1) streaming state (terminal_state connected) +
        (2) historical probe nhỏ (5 nến M1, 1 call, qua throttle ≥5s + 429 rule).

        FAIL = warn only (fail-open: kênh streaming chính đã mở, probe lịch sử
        chỉ có tính chất chẩn đoán đường ống, không chặn boot)."""
        ts = self._streaming_state()
        stream_ok = ts is not None and bool(getattr(ts, "connected", False))
        hist_ok = False
        n_hist = 0
        try:
            probe = await self.fetch_candles(symbols[0], Timeframe.M1, limit=5)
            n_hist = len(probe)
            hist_ok = n_hist > 0
        except Exception as e:
            logger.warning(f"[PIPELINE] historical probe fail: {type(e).__name__}: {str(e)[:100]}")
        ok = stream_ok and hist_ok
        logger.info(
            f"[PIPELINE] {'THÔNG ✓ (stream OK + hist probe OK)' if ok else 'KHÔNG THÔNG (warn, fail-open)'} · "
            f"stream_connected={stream_ok} · hist_probe={n_hist}/5 M1 · "
            f"throttle ≥{self._hist_min_interval:.0f}s giữa 2 lần fetch + 429 recommendedRetryTime"
        )
        return ok

    async def ensure_market_watch(self, symbols: List[str]) -> bool:
        """MARKET-WATCH-FIRST-SEQ (2026-09-22): pre-open the streaming
        connection, sync the terminal, and add symbols to Market Watch
        BEFORE historical candle fetch.

        Per MetaAPI docs the cloud terminal needs a few seconds to load its
        Market Watch from the broker; fetch/subscribe fired too early time
        out. Idempotent: a later start_streaming() on the same connection
        skips already-subscribed symbols and only starts the stream monitor.
        """
        self._stream_symbols = symbols
        logger.info(
            f"[METAAPI] Pre-subscribing Market Watch {symbols} "
            f"(terminal sync + market-watch BEFORE gap-fill)..."
        )
        return await self._start_streaming_internal(symbols, start_monitor=False)

    @staticmethod
    def _is_broker_not_connected_error(err: Any) -> bool:
        """MetaAPI raises this when the MT5 terminal behind the account has no
        broker session yet — typically a slow deploy, a dormant weekend
        account, or an SDK region that does not match the account region."""
        m = str(err).lower()
        return (
            'not connected to broker' in m
            or 'account is not connected' in m
            or 'does not match the account region' in m
        )

    @staticmethod
    def _broker_not_connected_hint() -> str:
        return (
            "account is not connected to broker yet OR SDK settings do not "
            "match the account region — verify the account's MetaApi region "
            "matches the token/endpoint region "
            "(https://metaapi.cloud/docs/client/regions/) and that the MT5 "
            "account credentials are still valid on the broker side"
        )

    def _broker_status_snapshot(self) -> str:
        """One-line terminal-state snapshot for diagnostics logs."""
        ts = self._streaming_state()
        if ts is None:
            return "terminal_state=None (no sync push received yet)"
        return (
            f"connected={getattr(ts, 'connected', None)}, "
            f"connectedToBroker={getattr(ts, 'connected_to_broker', None)}, "
            f"synchronizationStatus={getattr(ts, 'synchronization_status', None)}"
        )

    async def _wait_for_streaming_sync(
        self, max_retries: Optional[int] = None
    ) -> bool:
        """wait_synchronized() with retries + linear backoff
        (10s, 20s, 30s, 40s, 50s). Returns True only if sync actually completed.
        `max_retries` overrides the client default (used by stuck-sync recovery
        to keep the post-redeploy retry budget tight).

        [WS-AMP-1 2026-09-22, F3] Fast path: if the SDK already reports the
        streaming connection as synchronized, re-requesting cloud sync is
        pointless and can collide with a stuck terminal-cloud state (incident
        09-22 21:14/22:40 — "synchronization id None"). Skip the wait loop.
        """
        if max_retries is None:
            max_retries = self._stream_sync_max_retries
        sync_timeout = self._stream_sync_timeout
        try:
            sc = self.stream_connection
            fn = getattr(sc, "is_synchronized", None)
            if fn is not None:
                sync_state = fn()
                if asyncio.iscoroutine(sync_state):
                    # SDK streaming connection: async is_synchronized()
                    sync_state = await asyncio.wait_for(
                        sync_state, timeout=min(sync_timeout, 10.0))
                if sync_state:
                    logger.info(
                        "[METAAPI] Streaming already synchronized — skipping "
                        "sync wait (fast path)")
                    return True
        except Exception:
            pass  # check unavailable / errored — fall through to bounded retries
        for retry_count in range(max_retries + 1):
            attempt = retry_count + 1
            logger.info(
                f"[METAAPI] Streaming sync attempt {attempt}/{max_retries + 1} "
                f"(timeout={sync_timeout}s)..."
            )
            try:
                try:
                    # metaapi_cloud_sdk: bounded dict form (SynchronizationOptions)
                    await self.stream_connection.wait_synchronized(
                        {'timeoutInSeconds': int(sync_timeout)}
                    )
                except TypeError:
                    # SDK variant without opts arg: bound via asyncio wrapper
                    await asyncio.wait_for(
                        self.stream_connection.wait_synchronized(),
                        timeout=sync_timeout
                    )
                logger.info(f"[METAAPI] Streaming synchronized on attempt {attempt}")
                return True
            except asyncio.TimeoutError:
                logger.warning(
                    f"[METAAPI] Sync attempt {attempt}/{max_retries + 1} timed "
                    f"out after {sync_timeout}s | {self._broker_status_snapshot()}"
                )
            except Exception as e:
                # SDK TimeoutException / connection errors → bounded retry
                logger.warning(
                    f"[METAAPI] Sync attempt {attempt}/{max_retries + 1} failed: "
                    f"{type(e).__name__}: {e} | {self._broker_status_snapshot()}"
                )
            if retry_count < max_retries:
                backoff = self._stream_sync_backoff_step * (retry_count + 1)
                backoff = min(backoff, self._stream_sync_backoff_step * max_retries)
                logger.info(
                    f"[METAAPI] Backoff {backoff:.0f}s before sync retry "
                    f"{retry_count + 1}/{max_retries}..."
                )
                await asyncio.sleep(backoff)
        logger.error(
            f"[METAAPI] Streaming sync FAILED after {max_retries + 1} attempts "
            f"| {self._broker_status_snapshot()}"
        )
        return False

    async def _wait_for_broker_ready(
        self, timeout: Optional[float] = None
    ) -> bool:
        """Poll terminal_state until connectedToBroker=True (or timeout).

        subscribe_to_market_data silently fails (or throws "account is not
        connected to broker yet") while the MT5 terminal has no broker session,
        so broker readiness is an explicit gate BEFORE any subscription."""
        timeout = self._broker_ready_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        poll = 0
        last_snapshot = None
        while True:
            poll += 1
            ts = self._streaming_state()
            connected = getattr(ts, 'connected', False) if ts is not None else False
            broker_connected = (
                getattr(ts, 'connected_to_broker', False) if ts is not None else False
            )
            snapshot = self._broker_status_snapshot()
            if snapshot != last_snapshot:
                logger.info(
                    f"[METAAPI] Broker readiness poll {poll}: {snapshot}"
                )
                last_snapshot = snapshot
            if broker_connected:
                logger.info(
                    f"[METAAPI] Broker connection READY "
                    f"(connectedToBroker=true after {poll} poll(s))"
                )
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    f"[METAAPI] Broker connection NOT ready after {timeout:.0f}s "
                    f"({poll} polls) | {snapshot}"
                )
                return False
            await asyncio.sleep(min(self._broker_ready_poll_interval, remaining))

    async def _start_streaming_internal(
        self, symbols: List[str], start_monitor: bool = True
    ) -> bool:
        try:
            logger.info(f"[METAAPI] Starting streaming for {symbols}")
            if self.account is None:
                logger.error(
                    "[METAAPI] Cannot start streaming: account not initialized"
                )
                self._state.last_error = "account not initialized"
                return False

            # Fix 2026-09-21: Per official MetaAPI streaming example,
            # check account connection status and wait for broker connection
            # BEFORE getting streaming connection.
            # See: https://github.com/metaapi/metaapi-python-sdk/blob/main/examples/stream_quotes/stream_quotes.py
            try:
                # Check connection status before waiting
                if hasattr(self.account, 'connection_status') and self.account.connection_status != 'CONNECTED':
                    logger.info(
                        f"[METAAPI] Account connection_status={self.account.connection_status!r} "
                        f"— waiting for broker connection..."
                    )
                    await asyncio.wait_for(
                        self.account.wait_connected(),
                        timeout=self._deploy_timeout
                    )
                    logger.info(
                        f"[METAAPI] Account connected to broker "
                        f"(state={self.account.state!r})"
                    )
                elif self.account.state not in ('DEPLOYING', 'DEPLOYED'):
                    # Account not deployed yet, deploy first
                    logger.info(
                        f"[METAAPI] Account state={self.account.state!r} — deploying..."
                    )
                    await self.account.deploy()
                    logger.info(
                        "[METAAPI] Waiting for MetaAPI server to connect to broker "
                        f"(may take a couple of minutes, timeout={self._deploy_timeout}s)..."
                    )
                    await asyncio.wait_for(
                        self.account.wait_connected(),
                        timeout=self._deploy_timeout
                    )
                    logger.info(
                        f"[METAAPI] Account connected to broker "
                        f"(state={self.account.state!r})"
                    )
            except Exception as e:
                logger.error(f"[METAAPI] Failed to ensure broker connection: {e}")
                self._state.last_error = f"broker connection failed: {e}"
                return False

            if self.stream_connection is None:
                self.stream_connection = self.account.get_streaming_connection()

                # Apply proxy if configured
                if _PROXY_URL:
                    logger.info(f"[METAAPI] Using proxy: {_PROXY_URL}")
                    self.stream_connection.set_proxy(_PROXY_URL)

                # Apply SSL context for Mac
                if hasattr(self.stream_connection, 'set_ssl_context'):
                    self.stream_connection.set_ssl_context(_SSL_CONTEXT)
                    logger.info("[METAAPI] SSL context applied to streaming connection")

            # Step 1: WebSocket connect (idempotent — the SDK no-ops repeat calls,
            # so re-entering via start_streaming after ensure_market_watch is safe)
            logger.info("[METAAPI] Step 1/4: connecting streaming WebSocket...")
            await asyncio.wait_for(self.stream_connection.connect(), timeout=30)
            logger.info("[METAAPI] Step 1/4: streaming WebSocket connected")

            # ── STALL DIAGNOSTICS: wrap stream callbacks (gated by flag) ──
            if self._diag_logs_enabled():
                self._wrap_stream_callbacks()

            # Step 2: synchronization (retries, backoff 10/20/30/40/50s)
            logger.info("[METAAPI] Step 2/4: waiting for streaming sync...")
            synced = await self._wait_for_streaming_sync()

            # ── STUCK-SYNC ESCALATION (13-10 tối 21:xx, theo MetaApi docs) ──
            # Sync KÈO phía cloud: connectedToBroker=True nhưng
            # synchronizationStatus=None kéo dài → local terminal state rỗng →
            # subscribe "symbol does not exist". Retry wait_synchronized client-side
            # KHÔNG giải được (sự cố tối nay: 6×180s toàn fail, terminal state
            # không bao giờ rebuild). Remedy documented = restart terminal cloud
            # (redeploy = undeploy+deploy) + streaming WS connection MỚI.
            # Flag escalation chống redeploy storm: tối đa 1 lần/chu kỳ startup
            # (reset ở start_streaming công khai).
            if not synced and not self._stuck_sync_escalated:
                self._stuck_sync_escalated = True
                logger.warning(
                    "[METAAPI] Streaming sync STUCK (synchronizationStatus=None) → "
                    "escalating ONCE: terminal redeploy + fresh WS connection"
                )
                if await self.recover_streaming_after_stuck_sync():
                    synced = await self._wait_for_streaming_sync(max_retries=2)

            # Step 3: explicit broker-readiness gate BEFORE subscribing.
            # This is the terminal that carries the diagnostic
            # "account is not connected to broker yet or SDK settings you use
            # does not match the account region" — a sync miss alone is NOT
            # fatal if the broker link is up, but subscribing without it is.
            logger.info("[METAAPI] Step 3/4: waiting for broker connection readiness...")
            broker_ready = await self._wait_for_broker_ready()
            if not broker_ready:
                err = "account not connected to broker"
                self._state.last_error = err
                if synced:
                    logger.error(
                        f"[METAAPI] Step 3/4: sync OK but broker NOT connected — "
                        f"aborting before subscribe. {self._broker_not_connected_hint()}"
                    )
                else:
                    logger.error(
                        f"[METAAPI] Step 3/4: sync FAILED and broker NOT "
                        f"connected — aborting before subscribe. "
                        f"{self._broker_not_connected_hint()}"
                    )
                return False
            if not synced:
                logger.warning(
                    "[METAAPI] Step 3/4: sync did not complete within retry "
                    "budget, but broker IS connected — proceeding to subscribe"
                )
            logger.info("[METAAPI] Step 3/4: broker connection gate passed")

            # Step 4: market-data subscriptions
            logger.info(
                f"[METAAPI] Step 4/4: subscribing to market data for {symbols}..."
            )
            subscribed: List[str] = []
            failed: List[str] = []
            for symbol in symbols:
                if symbol in self._market_watch_symbols:
                    logger.info(
                        f"[METAAPI] {symbol} already in Market Watch — "
                        f"subscription confirmed, skipping re-subscribe"
                    )
                    subscribed.append(symbol)
                    self._log_subscribe(symbol)
                    continue
                attempt = 0
                while attempt < self._subscribe_max_attempts:
                    attempt += 1
                    try:
                        logger.info(
                            f"[METAAPI] Subscribing to {symbol} "
                            f"(attempt {attempt}/{self._subscribe_max_attempts})..."
                        )
                        await asyncio.wait_for(
                            self.stream_connection.subscribe_to_market_data(symbol),
                            timeout=self._subscribe_timeout
                        )
                        subscribed.append(symbol)
                        self._market_watch_symbols.add(symbol)
                        self._log_subscribe(symbol)
                        logger.info(f"[METAAPI] Subscribed to {symbol} (Market Watch)")
                        break
                    except Exception as e:
                        error_str = str(e)
                        if self._is_broker_not_connected_error(error_str):
                            logger.error(
                                f"[METAAPI] Subscribe {symbol} rejected "
                                f"(attempt {attempt}): {error_str}"
                            )
                            logger.error(
                                f"[METAAPI] {self._broker_not_connected_hint()}"
                            )
                            if attempt >= self._subscribe_max_attempts:
                                break
                            logger.info(
                                "[METAAPI] Re-waiting for broker connection "
                                "readiness before retry..."
                            )
                            if await self._wait_for_broker_ready(
                                timeout=self._broker_ready_timeout
                            ):
                                continue
                            logger.error(
                                f"[METAAPI] Broker still not connected — "
                                f"aborting subscription for {symbol}"
                            )
                            break
                        elif 'ValidationException: symbol does not exist' in error_str:
                            if attempt < self._subscribe_max_attempts:
                                logger.warning(
                                    f"[METAAPI] Symbol {symbol} validation error, "
                                    f"retry {attempt}/{self._subscribe_max_attempts}: {e}"
                                )
                                await asyncio.sleep(2 * attempt)
                                continue
                            logger.error(
                                f"[METAAPI] Symbol {symbol} failed after "
                                f"{self._subscribe_max_attempts} attempts: {e}"
                            )
                            failed.append(symbol)
                            break
                        else:
                            logger.error(
                                f"[METAAPI] Subscription error for {symbol}: "
                                f"{type(e).__name__}: {e}"
                            )
                            logger.error(
                                f"[METAAPI] Subscription traceback: {traceback.format_exc()}"
                            )
                            if self._is_broker_not_connected_error(traceback.format_exc()):
                                # some SDK paths only expose the reason in the trace
                                self._state.last_error = "account not connected to broker"
                            failed.append(symbol)
                            break

            # Start streaming monitor (owned by start_streaming; ensure_market_watch
            # pre-subscribes without a monitor so gap-fill runs first)
            if start_monitor:
                self._start_stream_monitor()
            logger.info(
                f"[METAAPI] Streaming startup complete: subscribed={subscribed}, "
                f"failed={failed}, {self._broker_status_snapshot()}"
            )
            if not subscribed and symbols:
                self._state.last_error = f"all subscriptions failed: {failed}"
                logger.error(
                    f"[METAAPI] No symbol subscribed — reporting streaming startup as FAILED"
                )
                return False
            return True
        except Exception as e:
            self._state.last_error = str(e)
            logger.error(f"[METAAPI] Streaming failed: {type(e).__name__}: {e}")
            if self._is_broker_not_connected_error(e):
                logger.error(f"[METAAPI] {self._broker_not_connected_hint()}")
            logger.error(f"[METAAPI] Streaming traceback: {traceback.format_exc()}")
            logger.error(f"[METAAPI] Final state: {self._broker_status_snapshot()}")
            return False

    def _diag_logs_enabled(self) -> bool:
        """Return True when STALL_DIAG_LOGS flag is ON, False otherwise."""
        # Check via settings flag; default OFF → zero output when flag is OFF
        return getattr(self, '_stall_diag_logs_flag', False)

    # ---------------------------------------------------------------------------
    # Callback wrappers — each wrapper preserves the original SDK callback (if any)
    # and adds diagnostics gated by STALL_DIAG_LOGS.  Zero behavioural change
    # when the flag is OFF.
    # ---------------------------------------------------------------------------

    def _wrap_stream_callbacks(self):
        """Wrap on_tick, on_connected, on_disconnected with diagnostics."""
        ws = self.stream_connection

        # --- on_tick wrapper (WS_CHUNK_GAP) ---
        original_on_tick = getattr(ws, 'on_tick', None)

        async def _on_tick_wrapper(instance_index, price):
            if not self._diag_logs_enabled():
                if original_on_tick and asyncio.iscoroutinefunction(original_on_tick):
                    await original_on_tick(instance_index, price)
                elif original_on_tick:
                    original_on_tick(instance_index, price)
                return

            symbol = price.get('symbol', 'unknown') if isinstance(price, dict) else 'unknown'
            now = time.monotonic()

            # Track last chunk arrival per symbol for gap detection
            last = self._last_chunk_ts.get(symbol, 0.0)
            gap = now - last
            self._last_chunk_ts[symbol] = now

            # Log interval (informational)
            logger.debug(
                f"[STALL_DIAG] tick arrival symbol={symbol} gap_seconds={gap:.3f}"
            )

            # WARN if gap > 5 seconds
            if gap > 5.0:
                logger.warning(
                    f"[STALL_DIAG] WS_CHUNK_GAP: symbol={symbol} "
                    f"gap_seconds={gap:.1f} last_chunk_ts={last:.1f}"
                )

            if original_on_tick:
                if asyncio.iscoroutinefunction(original_on_tick):
                    await original_on_tick(instance_index, price)
                else:
                    # synchronous original — run in thread so we don't block
                    asyncio.create_task(self._run_sync_original(original_on_tick, instance_index, price))

        ws.on_tick = _on_tick_wrapper

        # --- on_connected wrapper (WS_LIFECYCLE) ---
        original_on_connected = getattr(ws, 'on_connected', None)

        def _on_connected_wrapper():
            if not self._diag_logs_enabled():
                if original_on_connected:
                    if asyncio.iscoroutinefunction(original_on_connected):
                        # fire-and-forget
                        asyncio.ensure_future(original_on_connected())
                    else:
                        original_on_connected()
                return

            self._ws_connect_ts = time.monotonic()
            logger.info(
                f"[STALL_DIAG] WS_LIFECYCLE: connected at {self._ws_connect_ts:.1f}s"
            )
            if original_on_connected:
                if asyncio.iscoroutinefunction(original_on_connected):
                    asyncio.ensure_future(original_on_connected())
                else:
                    original_on_connected()

        ws.on_connected = _on_connected_wrapper

        # --- on_disconnected wrapper (WS_LIFECYCLE) ---
        original_on_disconnected = getattr(ws, 'on_disconnected', None)

        def _on_disconnected_wrapper(close_code, close_reason):
            if not self._diag_logs_enabled():
                if original_on_disconnected:
                    if asyncio.iscoroutinefunction(original_on_disconnected):
                        asyncio.ensure_future(original_on_disconnected(close_code, close_reason))
                    else:
                        original_on_disconnected(close_code, close_reason)
                return

            self._ws_disconnect_ts = time.monotonic()
            logger.info(
                f"[STALL_DIAG] WS_LIFECYCLE: disconnected "
                f"code={close_code} reason={close_reason} "
                f"at {self._ws_disconnect_ts:.1f}s"
            )
            if original_on_disconnected:
                if asyncio.iscoroutinefunction(original_on_disconnected):
                    asyncio.ensure_future(original_on_disconnected(close_code, close_reason))
                else:
                    original_on_disconnected(close_code, close_reason)

        ws.on_disconnected = _on_disconnected_wrapper

    async def _run_sync_original(self, func, *args):
        """Run a synchronous callback in an async context."""
        try:
            func(*args)
        except Exception as e:
            logger.warning(f"[STALL_DIAG] sync callback error: {e}")

    def _sample_terminal_status(self):
        """Sample account.connection_status ~every 60s while streaming active."""
        now = time.monotonic()
        if now - self._terminal_status_ts < 60.0:
            return
        self._terminal_status_ts = now
        try:
            conn_status = 'unknown'
            if self.account and hasattr(self.account, 'connection_status'):
                conn_status = self.account.connection_status
            elif self.stream_connection:
                ts = self._streaming_state()
                if ts is not None:
                    conn_status = str(getattr(ts, 'connected', None))
            logger.info(
                f"[STALL_DIAG] TERMINAL_STATUS: connection_status={conn_status} "
                f"at {self._terminal_status_ts:.1f}s"
            )
        except Exception as e:
            logger.warning(f"[STALL_DIAG] TERMINAL_STATUS sample failed: {e}")

    def _subscribe_log(self, symbol: str, timeframe: Optional[str] = None):
        """Log subscribe/unsubscribe sequence event (SUB_SEQUENCE)."""
        entry = {
            'timestamp': time.monotonic(),
            'symbol': symbol,
            'timeframe': timeframe or 'market_data',
        }
        self._subscribe_seq.append(entry)
        logger.info(
            f"[STALL_DIAG] SUB_SEQUENCE: symbol={symbol} "
            f"timeframe={timeframe or 'market_data'} seq_len={len(self._subscribe_seq)}"
        )

    def _get_symbol_timeframe(self, symbol: str) -> Optional[str]:
        """Helper to determine timeframe for a subscribed symbol."""
        # Symbols subscribed via subscribe_to_market_data are market_data (no specific TF)
        return None

    # ---------------------------------------------------------------------------
    # Terminal status sampling integration into the stream monitor loop
    # ---------------------------------------------------------------------------

    async def _stream_monitor_loop(self):
        """Monitor streaming connection and auto-reconnect if dead."""
        logger.info("[METAAPI] Stream monitor loop running")
        while True:
            try:
                await asyncio.sleep(self._stream_monitor_interval)
                if not await self._is_stream_healthy():
                    logger.warning("[METAAPI] Streaming connection unhealthy, attempting reconnect...")
                    await self._reconnect_stream()
                # Sample terminal status every 60s (approximately — every 6th monitor interval)
                if self._diag_logs_enabled():
                    self._sample_terminal_status()
            except asyncio.CancelledError:
                logger.info("[METAAPI] Stream monitor cancelled")
                break
            except Exception as e:
                logger.error(f"[METAAPI] Stream monitor error: {e}")

    # ---------------------------------------------------------------------------
    # Subscribe logging — called from subscribe flow
    # ---------------------------------------------------------------------------

    def _log_subscribe(self, symbol: str):
        """Log subscribe event (SUB_SEQUENCE)."""
        if self._diag_logs_enabled():
            self._subscribe_log(symbol, timeframe='market_data')

    def _start_stream_monitor(self):
        """Start background task to monitor streaming connection health."""
        if self._stream_monitor_task and not self._stream_monitor_task.done():
            return
        self._stream_monitor_task = asyncio.create_task(self._stream_monitor_loop())
        logger.info("[METAAPI] Stream monitor started")

    async def _stream_monitor_loop(self):
        """Monitor streaming connection and auto-reconnect if dead."""
        logger.info("[METAAPI] Stream monitor loop running")
        while True:
            try:
                await asyncio.sleep(self._stream_monitor_interval)
                if not await self._is_stream_healthy():
                    logger.warning("[METAAPI] Streaming connection unhealthy, attempting reconnect...")
                    await self._reconnect_stream()
            except asyncio.CancelledError:
                logger.info("[METAAPI] Stream monitor cancelled")
                break
            except Exception as e:
                logger.error(f"[METAAPI] Stream monitor error: {e}")

    async def _is_stream_healthy(self) -> bool:
        """Check if streaming connection is alive and synchronized."""
        if not self.stream_connection:
            return False
        try:
            # Check server-side health first (MetaAPI health monitor)
            if hasattr(self.stream_connection, 'health_monitor'):
                hm = self.stream_connection.health_monitor
                if hasattr(hm, 'server_health_status'):
                    try:
                        hs = hm.server_health_status
                        if hs and not hs.get('rpcApiHealthy', True):
                            logger.warning("[METAAPI] Server health unhealthy: rpcApiHealthy=False")
                            return False
                    except Exception:
                        pass
            # Check if WebSocket is connected
            ws = getattr(self.stream_connection, '_websocket', None)
            if ws and hasattr(ws, 'connected'):
                if not ws.connected:
                    close_code = getattr(ws, 'close_code', None)
                    close_reason = getattr(ws, 'close_reason', None)
                    if close_code is not None:
                        logger.warning(f"[METAAPI] WebSocket closed with code {close_code}, reason: {close_reason}")
                    else:
                        logger.warning("[METAAPI] WebSocket disconnected")
                    return False
            # Check if synchronized
            ts = self._streaming_state()
            return ts is not None
        except Exception:
            return False

    async def _reconnect_stream(self) -> bool:
        """Reconnect streaming WebSocket connection with exponential backoff + health check."""
        async with self._stream_reconnect_lock:
            # Honor broker recommended retry time if available
            now = time.monotonic()
            if self._recommended_retry_after > now:
                wait = self._recommended_retry_after - now
                logger.info(f"[METAAPI] Honoring recommendedRetryTime, waiting {wait:.1f}s")
                await asyncio.sleep(wait)
                self._recommended_retry_after = 0.0
            
            # Exponential backoff with jitter
            if now - self._last_stream_reconnect < self._stream_reconnect_min_interval:
                await asyncio.sleep(0.5)
            base = self._stream_reconnect_base * (2 ** self._stream_reconnect_attempt)
            backoff = min(base, self._stream_reconnect_max_interval)
            jitter = backoff * 0.1 * random.random()  # 0-10% jitter
            wait = backoff + jitter
            
            self._last_stream_reconnect = now
            self._stream_reconnect_attempt += 1
            
            old = self.stream_connection
            self.stream_connection = None
            self._market_watch_symbols = set()  # fresh connection → full re-subscribe
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            
            try:
                success = await self._start_streaming_internal(self._stream_symbols)
                if success:
                    self._stream_seq += 1
                    self._stream_reconnect_attempt = 0  # reset on success
                    # 13-10 tối 21:xx: listeners là per-connection (SDK) → swap
                    # connection xong phải re-mount, không thì tick feed chết thầm.
                    self._readd_stream_listeners()
                    logger.info(f"[METAAPI] Streaming connection re-established (seq {self._stream_seq})")
                return success
            except Exception as e:
                logger.error(f"[METAAPI] Stream reconnect failed: {e}")
                return False

    def add_stream_listener(self, listener):
        """Register a synchronization listener on the streaming connection.

        The MetaAPI websocket client invokes EVERY listener callback
        (on_broker_connection_status_changed, on_health_status, ...) on every
        registered listener. Duck-typed listeners missing those methods caused
        AttributeError storms on each broker-status/health event, so anything
        not implementing the full SynchronizationListener interface is wrapped
        in a delegating adapter that no-ops the missing callbacks."""
        if not self.stream_connection:
            logger.warning(
                "[METAAPI] add_stream_listener: no streaming connection yet — "
                "listener not registered"
            )
            return
        if not isinstance(listener, SynchronizationListener):
            missing = [m for m in _CORE_LISTENER_METHODS if not callable(getattr(listener, m, None))]
            if missing:
                logger.warning(
                    "[METAAPI] Listener %r missing callbacks %s — wrapping in "
                    "safe adapter to avoid AttributeError",
                    type(listener).__name__, missing
                )
                listener = _SafeSynchronizationListener(listener)
        # 13-10 tối 21:xx — registry: SDK listeners là per-connection, swap
        # streaming connection (reconnect/recover) mà không re-attach = tick feed
        # chết thầm. Ghi lại để _readd_stream_listeners() re-mount khi cần.
        if listener not in self._stream_listeners:
            self._stream_listeners.append(listener)
        self.stream_connection.add_synchronization_listener(listener)

    def _readd_stream_listeners(self) -> None:
        """Re-attach every registered listener onto the current streaming
        connection (no-op khi connection None)."""
        if not self.stream_connection:
            return
        for lst in list(self._stream_listeners):
            try:
                self.stream_connection.add_synchronization_listener(lst)
            except Exception as e:
                logger.warning(f"[METAAPI] re-attach listener {type(lst).__name__} failed: {e}")

    async def recover_streaming_after_stuck_sync(self) -> bool:
        """Doc-compliant WS reconnect khi streaming sync KÈO (MetaApi:
        synchronizationStatus=None dù connectedToBroker=True → terminal state
        phía cloud không đồng bộ → subscribe 'symbol does not exist').

        Trình tự theo docs: close() connection cũ → restart terminal cloud
        (redeploy = undeploy+deploy) → wait_connected() → get_streaming_connection()
        MỚI → connect() → re-attach listeners. (Vị thế + TP an toàn: sống bên
        broker, không phải trong terminal cloud.)
        """
        old = self.stream_connection
        self.stream_connection = None
        self._market_watch_symbols = set()
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass
        # Best-effort terminal restart: clears the stuck cloud terminal state ON PLANS
        # WITH PERMISSION. Trên plan bị gate (Forbidden), log + tiếp tục — fresh
        # connection + re-sync bên dưới vẫn là reconnect procedure đúng docs, và khi
        # terminal state tự hồi (console/gateway) nó sẽ đồng bộ được.
        try:
            logger.info("[METAAPI] Terminal redeploy (undeploy+deploy) scheduled...")
            await self.account.redeploy()
            await asyncio.wait_for(
                self.account.wait_connected(), timeout=self._deploy_timeout
            )
            logger.info("[METAAPI] Terminal reconnected to broker after redeploy")
        except Exception as e:
            logger.warning(
                f"[METAAPI] Terminal redeploy not available: {type(e).__name__} — "
                "proceeding with fresh WS connection + re-sync only"
            )
        try:
            self.stream_connection = self.account.get_streaming_connection()
            if _PROXY_URL:
                self.stream_connection.set_proxy(_PROXY_URL)
            if hasattr(self.stream_connection, "set_ssl_context"):
                self.stream_connection.set_ssl_context(_SSL_CONTEXT)
            await asyncio.wait_for(self.stream_connection.connect(), timeout=30)
            self._readd_stream_listeners()
            logger.info("[METAAPI] Fresh streaming WS connection established (post-redeploy)")
            return True
        except Exception as e:
            logger.error(f"[METAAPI] Fresh streaming connection failed: {type(e).__name__}: {e}")
            return False

    async def get_positions(self) -> List[Dict]:
        # 1. Prefer streaming terminal_state (free, push-driven — no RPC credits).
        #    Only trust it once positionsInitialized=True (else [] could be a
        #    pre-sync empty state → overtrading risk). Access is defensive:
        #    _combined_state is private, so fall back to RPC on any doubt.
        ts = self._streaming_state()
        if ts is not None:
            try:
                initialized = ts._combined_state.get('positionsInitialized', False)
                if initialized:
                    positions = ts.positions
                    # MetaAPI SDK returns dict {position_id: position_data} or list
                    if isinstance(positions, dict):
                        return list(positions.values()) or []
                    elif isinstance(positions, list):
                        return positions or []
                    return []
            except Exception as e:
                logger.warning(f"[METAAPI] Streaming positions read failed: {e}")
        # 2. Fallback RPC (boot / reconnect edge)
        if not self.rpc_connection:
            return []
        # S4-BOOT (14/10 19:xx): RPC chưa synchronized (cloud websocket down) → SDK
        # latency_service.wait_connected_instance HANG vô hạn (proven: boot 18:49/19:08
        # stuck đúng dòng này). Guard → return [] (flat-verified user 14/10; streaming
        # state branch ở trên là nguồn chính khi live). Trading calls vẫn self-heal
        # qua _reconnect_rpc; guard tự nhả khi is_synchronized=True (re-sync OK).
        if not self._state.is_synchronized:
            logger.warning("[METAAPI] get_positions: RPC chưa synchronized (cloud down) → return [] (không hang; self-heal khi recover)")
            return []
        return await self.rpc_connection.get_positions()

    async def get_orders(self) -> List[Dict]:
        if not self.rpc_connection:
            return []
        return await self.rpc_connection.get_orders()

    async def get_history_deals_by_ticket(self, ticket_id: str) -> List[Dict]:
        """L3 Settlement: fetch the REAL executed deal(s) for a position ticket
        from broker history (exit price, profit, commission, swap, reason).

        Broker is the absolute truth — this is what overwrites the local trade
        record after a position closes (Patch 2). Requires the MT5 terminal to
        have settled the deal (~5s after close), so callers wait before querying.

        Primary lookup is by position id (get_deals_by_position — our stored
        ticket IS the broker positionId); falls back to order-ticket lookup.

        NOTE: the SDK returns a wrapper dict like
        ``{"deals": [...], "synchronizing": false}`` (and may also expose a
        MetatraderDeals model with a .deals attr) — we must unwrap BOTH shapes
        and return the bare deal list, never the wrapper (wrapping it made a
        closing deal look "settled" with all-zero fields — Patch 2 fix).
        """
        if not self.rpc_connection:
            return []

        def _unwrap(result):
            if result is None:
                return []
            if isinstance(result, dict):
                inner = result.get("deals")
                if isinstance(inner, list):
                    return inner
                return [] if "deals" in result else [result]
            raw = getattr(result, "deals", None)
            if isinstance(raw, list):
                return raw
            return [] if raw is None else [result]

        try:
            result = await self.rpc_connection.get_deals_by_position(ticket_id)
            deals = _unwrap(result)
            if deals:
                return deals
        except Exception as e:
            logger.warning(f"[METAAPI] get_deals_by_position({ticket_id}) failed: {e}")
        try:
            result = await self.rpc_connection.get_deals_by_ticket(ticket_id)
            return _unwrap(result)
        except Exception as e:
            logger.error(f"[METAAPI] get_history_deals_by_ticket({ticket_id}) failed: {e}")
            return []

    async def get_history_deals(self, from_ts: int) -> List[Dict]:
        """L3 Audit: fetch ALL deal records (not per-ticket) since from_ts.
        Used by AuditorDaemon to compute Real_Broker_PnL for PnL Drift reconciliation.

        Uses SDK `get_deals_by_time_range` (the ONLY time-range API — bare
        `get_deals` does not exist). Returns bare list of deal dicts."""
        if not self.rpc_connection:
            return []
        # S4-BOOT (14/10 19:xx): guard tương tự get_positions — RPC chưa synchronized
        # (cloud down) → SDK get_deals_by_time_range HANG vô hạn → skip (boot backfill
        # bỏ qua, re-run khi recover; KHÔNG đổi logic PnL/dedup của L3 Audit).
        if not self._state.is_synchronized:
            logger.warning("[METAAPI] get_history_deals: RPC chưa synchronized (cloud down) → return [] (boot backfill skip, re-sync khi recover)")
            return []
        await self._throttle_historical()  # USER 14/10: ≥5s giữa 2 lần gọi lịch sử (tuân rate-limit)
        try:
            from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            result = await self.rpc_connection.get_deals_by_time_range(from_dt, now_dt)
            if result is None:
                return []
            if isinstance(result, dict) and "deals" in result:
                return result["deals"] if isinstance(result["deals"], list) else []
            raw = getattr(result, "deals", None)
            if isinstance(raw, list):
                return raw
            return [] if raw is None else [result]
        except TooManyRequestsException as e:  # 429 (docs: honor recommendedRetryTime)
            await self._wait_for_429(e, f"get_history_deals({from_ts})")
            return []  # re-run cycle boot kế (INSERT OR IGNORE idempotent)
        except Exception as e:
            logger.warning(f"[METAAPI] get_history_deals({from_ts}) failed: {e}")
            return []

    @staticmethod
    def _is_connection_closed(err: Exception) -> bool:
        """MetaAPI SDK raises this PRE-FLIGHT error when the RPC (trading)
        connection object is already closed. It is thrown before the request
        reaches the broker, so a single retry after reconnect cannot duplicate
        an order — which is what makes self-heal safe on a real account."""
        m = str(err).lower()
        return "this connection has been closed" in m or "create a new connection" in m

    @staticmethod
    async def _rpc_wait_synchronized(conn, timeout: float) -> None:
        """Bounded RPC terminal sync. metaapi_cloud_sdk accepts a native
        ``timeout_in_seconds`` kwarg; for SDK variants without it the
        unbounded coroutine is wrapped in asyncio.wait_for (Python 3.9-safe)."""
        try:
            await conn.wait_synchronized(timeout_in_seconds=timeout)
        except TypeError:
            await asyncio.wait_for(conn.wait_synchronized(), timeout=timeout)

    async def _reconnect_rpc(self, after_seq: int = -1) -> bool:
        """Rebuild the RPC trading connection after it has closed.

        Re-fetches a FRESH account object first (the cached ``self.account``
        would hand back the same dead connection singleton), then connects and
        re-synchronizes. Serialized by a lock and de-duplicated by ``_rpc_seq``:
        concurrent failures against the same dead generation trigger exactly ONE
        rebuild, later callers simply reuse the restored connection.
        ``after_seq`` = the seq the caller observed as dead. Returns True if a
        usable connection (seq > after_seq) exists afterwards.
        """
        async with self._rpc_reconnect_lock:
            if self._rpc_seq > after_seq and self.rpc_connection is not None:
                return True
            if time.monotonic() - self._last_rpc_reconnect < self._rpc_reconnect_min_interval:
                await asyncio.sleep(0.5)
                if self._rpc_seq > after_seq and self.rpc_connection is not None:
                    return True
            self._last_rpc_reconnect = time.monotonic()
            old = self.rpc_connection
            self.rpc_connection = None
            self._state.is_connected = False
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            try:
                self.account = await asyncio.wait_for(
                    self.api.metatrader_account_api.get_account(self.account_id),
                    timeout=self._connect_timeout
                )
                conn = self.account.get_rpc_connection()
                await asyncio.wait_for(conn.connect(), timeout=self._connect_timeout)
                rpc_synced = False
                for attempt, sync_attempt_timeout in ((1, self._sync_timeout), (2, 60.0)):
                    try:
                        await self._rpc_wait_synchronized(conn, sync_attempt_timeout)
                        rpc_synced = True
                        break
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[METAAPI] RPC re-sync attempt {attempt} timed out "
                            f"after {sync_attempt_timeout:.0f}s"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[METAAPI] RPC re-sync attempt {attempt} failed: "
                            f"{type(e).__name__}: {e}"
                        )
                self.rpc_connection = conn
                self._rpc_seq += 1
                self._state.is_connected = True
                self._state.is_synchronized = rpc_synced
                self._state.last_error = None
                logger.info(
                    f"[METAAPI] RPC trading connection re-established "
                    f"(seq {self._rpc_seq}, synchronized={rpc_synced})"
                )
                return True
            except Exception as e:
                self._state.last_error = str(e)
                logger.error(f"[METAAPI] RPC reconnect failed: {e}")
                return False

    async def _rpc_call(self, name: str, coro_factory):
        """Run an RPC trading call, self-healing ONCE on a closed connection.

        ``coro_factory`` takes the live ``rpc_connection`` and returns a fresh
        awaitable (so it can be rebuilt for the retry). Returns ``(result, ok)``.
        Genuine broker rejections (market closed, invalid volume, ...) are NOT
        retried — only the pre-flight closed-connection error triggers
        reconnect+retry, so we never double-send an order.
        """
        if self.rpc_connection is None:
            if not await self._reconnect_rpc(after_seq=-1):
                logger.error(f"[METAAPI] {name} failed: no RPC connection")
                return None, False
        seen_seq = self._rpc_seq
        try:
            return await coro_factory(self.rpc_connection), True
        except Exception as e:
            if self._is_connection_closed(e):
                logger.warning(f"[METAAPI] {name}: RPC closed -> reconnecting once")
                if await self._reconnect_rpc(after_seq=seen_seq):
                    try:
                        return await coro_factory(self.rpc_connection), True
                    except Exception as e2:
                        logger.error(f"[METAAPI] {name} failed after reconnect: {e2}")
                        return None, False
                return None, False
            logger.error(f"[METAAPI] {name} failed: {e}")
            return None, False

    async def create_market_order(
        self,
        symbol: str,
        volume: float,
        direction: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        magic: int = 20260510,
        comment: Optional[str] = None
    ) -> Optional[Dict]:
        options = {'magic': magic}
        if comment:
            # comment + clientId sum <= 26 chars; strategy labels (SWING_LONG etc.) fit
            options['comment'] = comment[:20]

        def _factory(conn):
            if direction == 1:
                return conn.create_market_buy_order(
                    symbol=symbol, volume=volume,
                    stop_loss=stop_loss, take_profit=take_profit,
                    options=options
                )
            return conn.create_market_sell_order(
                symbol=symbol, volume=volume,
                stop_loss=stop_loss, take_profit=take_profit,
                options=options
            )

        result, _ok = await self._rpc_call("Order", _factory)
        return result

    async def close_position(self, position_id: str) -> Optional[Dict]:
        result, _ok = await self._rpc_call(
            f"Close {position_id}", lambda conn: conn.close_position(position_id)
        )
        return result

    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> bool:
        _result, ok = await self._rpc_call(
            f"Modify {position_id}",
            lambda conn: conn.modify_position(position_id, stop_loss, take_profit)
        )
        return ok

    async def refresh_quotes(self, symbols: List[str]) -> bool:
        _result, ok = await self._rpc_call(
            "Refresh quotes", lambda conn: conn.refresh_symbol_quotes(symbols)
        )
        return ok

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state.is_connected and self._state.is_synchronized

    async def shutdown(self):
        if self._stream_monitor_task and not self._stream_monitor_task.done():
            self._stream_monitor_task.cancel()
            try:
                await self._stream_monitor_task
            except asyncio.CancelledError:
                pass
        if self.stream_connection:
            try:
                await self.stream_connection.close()
            except Exception:
                pass
        if self.rpc_connection:
            try:
                await self.rpc_connection.close()
            except Exception:
                pass
        self._state.is_connected = False
        self._state.is_synchronized = False
        self._market_watch_symbols = set()
        logger.info("[METAAPI] Shutdown complete")


class MetaAPIClientFactory:
    _instance: Optional[MetaAPIClient] = None
    
    @classmethod
    async def create(cls, token: str, account_id: str, storage: Optional[SQLiteStorage] = None) -> MetaAPIClient:
        if cls._instance is None:
            cls._instance = MetaAPIClient(token, account_id, storage)
            await cls._instance.initialize()
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> Optional[MetaAPIClient]:
        return cls._instance
    
    @classmethod
    async def shutdown(cls):
        if cls._instance:
            await cls._instance.shutdown()
            cls._instance = None