#!/usr/bin/env python
"""metaapi_probe_resilient.py — MetaApi streaming probe, BẢN ĐÃ SỬA của code-sample
chính thức (~/Downloads/code-sample-python-streaming-b7a150a8...-3.zip/example.py).

Mục đích: probe "đường ống" MetaApi (REST → terminal → streaming → pipeline) bền bỉ
qua cả sự cố cloud (14/10: "not connected to broker" / WS flapping), theo đúng
MetaApi docs (SDK best-practices: 1 SDK instance long-living + close() đúng,
throttle initial syncs & historical requests, redeploy = cơ chế restart documented).

FIX vs sample gốc:
  F1 token/account chỉ từ env (fail-fast)          [sample: token nhúng trong file = lộ secret]
  F2 wait_connected / wait_synchronized có BUDGET  [sample: sync kẹt = treo mãi (đúng sự cố 14/10)]
  F3 429 → tôn recommendedRetryTime (cap 120s)
     + throttle ≥5s giữa 2 historical call        [sample: 6+ historical call ngay sau sync = rủi ro rate-limit]
  F4 escalation 1× `account.redeploy()` khi "not connected to broker" / sync stuck
                                                      [sample: không có gì → hang/error; docs: redeploy = restart terminal;
                                                       LƯU Ý: mỗi lần start server bị tính 6h phí theo docs]
  F5 chu kỳ retry backoff 30→60→120→300s, MAX_CYCLES (mặc định 5) rồi exit 1
                                                      [sample: 1-shot, in error, exit 0 = im lặng]
  F6 NO-TRADE mặc định — chỉ đặt lệnh khi TRADE=1 VÀ có TRADE_PRICE
                                                      [sample: đặt lệnh thật GBPUSD 0.07 KHÔNG điều kiện = NGUY HIỂM]
  F7 1 instance SDK + `api.close()` trong finally  [sample: leak SDK/connections — anti-pattern docs]
  F8 datetime UTC-aware                             [sample: datetime.now() naive]
  F9 SIGINT/SIGTERM shutdown sạch                  [sample: không xử lý]

Chạy:
  cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
  .venv/bin/python scripts/metaapi_probe_resilient.py
Env (bắt buộc): METAAPI_TOKEN, ACCOUNT_ID
Env (tuỳ chọn): SYMBOL (mặc định XAUUSDm) · TRADE=1 + TRADE_PRICE (bật đặt lệnh thật)
Exit: 0 = pipeline OK · 1 = hết MAX_CYCLES chưa OK · 130 = người dùng interrupt
"""
import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timezone

from metaapi_cloud_sdk import MetaApi
from metaapi_cloud_sdk.clients.error_handler import TooManyRequestsException

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("probe")

CONNECT_BUDGET = 180.0   # wait_connected (docs: "may take a couple of minutes")
SYNC_BUDGET = 180.0      # mỗi lần wait_synchronized
SYNC_ATTEMPTS = 3        # trước khi escalation redeploy (tuần tự, 1 kênh 1 lúc)
REDEPLOY_BUDGET = 120.0
HIST_MIN_INTERVAL = 5.0  # docs: "throttle ... historical data requests" (giống ORDER BOOT của bot)
DEFAULT_BACKOFFS = [30, 60, 120, 300]


class _Throttle:
    """F3: ≥5s giữa 2 lần gọi historical RPC (tất cả caller)."""

    def __init__(self, min_interval: float = HIST_MIN_INTERVAL):
        self.min_interval = min_interval
        self.last_call = 0.0

    async def wait(self) -> None:
        wait = self.min_interval - (time.monotonic() - self.last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_call = time.monotonic()


async def _wait_for_429(e: Exception) -> float:
    """F3: tôn MetaApi 429 recommendedRetryTime (docs rateLimiting) — cap 120s, fallback 30s."""
    wait = 30.0
    meta = getattr(e, "metadata", None)
    if isinstance(meta, dict) and meta.get("recommendedRetryTime"):
        try:
            until = datetime.fromisoformat(str(meta["recommendedRetryTime"]).replace("Z", "+00:00")).timestamp()
            wait = max(5.0, min(until - time.time(), 120.0))
        except Exception:
            pass
    log.warning(f"[PROBE] 429 rate-limit → chờ {wait:.0f}s (recommendedRetryTime, cap 120s)")
    await asyncio.sleep(wait)
    return wait


async def _fetch_probe_candles(account, symbol: str, throttle: _Throttle, retries: int = 2):
    """5 nến 1m (probe nhỏ, ~0.2 credit) — qua throttle + 429-aware (F3).
    NOTE: SDK docs — timeframe MT5 lowercase ('1m','5m',...), KHÔNG phải 'M1'."""
    for attempt in range(retries + 1):
        await throttle.wait()
        try:
            return await account.get_historical_candles(symbol, "1m", limit=5)
        except TooManyRequestsException as e:
            if attempt < retries:
                await _wait_for_429(e)
                continue
            log.error(f"[PROBE] historical probe 429 — hết retry: {str(e)[:100]}")
            return []
    return []


async def run_cycle(api, account, symbol: str, throttle: _Throttle,
                    trade_price, trade_enabled: bool, state: dict) -> bool:
    """1 chu kỳ: đảm bảo terminal DEPLOYED+CONNECTED → streaming sync → PIPELINE check.

    Trả True nếu pipeline THÔNG (terminal connected_to_broker + hist probe OK)."""
    # (F7) đóng streaming connection của cycle cũ (nếu có) — 1 connection/run, không churn
    old = state.get("stream")
    if old is not None:
        try:
            await old.close()
        except Exception:
            pass
        state["stream"] = None

    # (1) REST: đảm bảo terminal đã deploy (docs: deploy bị ignored nếu đã DEPLOYED)
    await account.reload()
    if account.state not in ("DEPLOYED", "DEPLOYING"):
        log.info(f"[PROBE] state={account.state} → deploy + wait_connected (budget {CONNECT_BUDGET:.0f}s)")
        await asyncio.wait_for(account.deploy(), timeout=120.0)
        await asyncio.wait_for(account.wait_connected(timeout_in_seconds=CONNECT_BUDGET), timeout=CONNECT_BUDGET + 60)

    # (2) Streaming: connect + sync TUẦN TỰ (3 attempt bounded trước khi escalation)
    conn = account.get_streaming_connection()
    try:
        await asyncio.wait_for(conn.connect(), timeout=60.0)
        synced = False
        for i in range(SYNC_ATTEMPTS):
            try:
                await asyncio.wait_for(conn.wait_synchronized(), timeout=SYNC_BUDGET)
                synced = True
                log.info(f"[PROBE] streaming synchronized (attempt {i + 1}/{SYNC_ATTEMPTS})")
                break
            except asyncio.TimeoutError:
                log.warning(f"[PROBE] streaming sync attempt {i + 1}/{SYNC_ATTEMPTS} timeout ({SYNC_BUDGET:.0f}s)")

        # (3) ESCALATION (F4): sync kẹt / terminal chưa nối broker → redeploy (1 lần/run)
        ts = conn.terminal_state
        broker_ok = bool(getattr(ts, "connected_to_broker", False)) if ts is not None else False
        if (not synced or not broker_ok) and not state["redeployed"]:
            log.warning(
                "[PROBE] sync stuck / not connected to broker → ESCALATION: "
                "account.redeploy() (cơ chế documented; LƯU Ý docs: mỗi lần start server = 6h phí)"
            )
            await asyncio.wait_for(account.redeploy(), timeout=REDEPLOY_BUDGET)
            state["redeployed"] = True
            await asyncio.wait_for(account.wait_connected(timeout_in_seconds=CONNECT_BUDGET), timeout=CONNECT_BUDGET + 60)
            try:
                await conn.close()  # kết nối cũ bỏ đi (docs: close connections không dùng nữa)
            except Exception:
                pass
            conn = account.get_streaming_connection()
            await asyncio.wait_for(conn.connect(), timeout=60.0)
            try:
                await asyncio.wait_for(conn.wait_synchronized(), timeout=SYNC_BUDGET)
                synced = True
                log.info("[PROBE] post-redeploy: streaming synchronized")
            except asyncio.TimeoutError:
                log.warning("[PROBE] post-redeploy: vẫn chưa sync → cycle kế tiếp (backoff)")
            ts = conn.terminal_state
            broker_ok = bool(getattr(ts, "connected_to_broker", False)) if ts is not None else False
            state["stream"] = conn  # lưu conn mới (không double-open connection cũ)
        else:
            state["stream"] = conn

        if not synced:
            return False

        # (4) PIPELINE CHECK (giống [PIPELINE] của bot): subscribe + historical probe nhỏ (throttle)
        await conn.subscribe_to_market_data(symbol)
        candles = await _fetch_probe_candles(account, symbol, throttle)
        price = ts.price(symbol)
        info = ts.account_information
        n_pos = len(ts.positions) if ts.positions is not None else 0
        equity = f"{info.equity:.2f}" if info is not None else "N/A"
        ok = broker_ok and len(candles) > 0
        log.info(
            f"[PROBE] PIPELINE {'THÔNG ✓' if ok else 'KHÔNG THÔNG'} · "
            f"connected_to_broker={broker_ok} · {symbol} last={price} · "
            f"hist_probe={len(candles)}/5 (1m) · positions_local_copy={n_pos} · "
            f"equity={equity}"
        )

        # (5) TRADE — CHỈ KHI TRADE=1 VÀ TRADE_PRICE có (F6: sample gốc = lệnh thật không điều kiện)
        if trade_enabled:
            if trade_price is None:
                log.error("[PROBE] TRADE=1 nhưng thiếu TRADE_PRICE → KHÔNG đặt lệnh (an toàn)")
                return ok
            log.warning(f"[PROBE] ⚠ TRADE=1: đặt limit BUY {symbol} @ {trade_price} (LOT 0.01, comment PROBE)")
            res = await conn.create_limit_buy_order(symbol, 0.01, trade_price, 0.0, 0.0, {
                "comment": "PROBE-TRADE",
                "clientId": f"PROBE_{int(time.time())}",
            })
            log.info(f"[PROBE] trade result: {res.get('stringCode') if isinstance(res, dict) else res}")
        return ok
    finally:
        # (F7/F9): không bao giờ leak streaming connection giữa các cycle (1 connection/run)
        pass


async def main() -> int:
    token = os.getenv("METAAPI_TOKEN")
    account_id = os.getenv("ACCOUNT_ID")
    if not token or not account_id:
        log.error("[PROBE] THIẾU METAAPI_TOKEN hoặc ACCOUNT_ID (env) — F1: không nhúng secret trong file")
        return 1
    symbol = os.getenv("SYMBOL", "XAUUSDm")
    trade_enabled = os.getenv("TRADE") == "1"
    try:
        trade_price = float(os.environ["TRADE_PRICE"]) if os.getenv("TRADE_PRICE") else None
    except ValueError:
        trade_price = None
    max_cycles = int(os.getenv("MAX_CYCLES", "5"))
    backoffs = [int(x) for x in os.getenv("BACKOFFS", "30,60,120,300").split(",")]

    api = MetaApi(token)  # F7: DUY NHẤT 1 instance, dùng xuyên suốt
    state = {"redeployed": False, "stream": None}
    throttle = _Throttle()
    stop = {"flag": False}
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # F9
        try:
            loop.add_signal_handler(sig, lambda: stop.__setitem__("flag", True))
        except NotImplementedError:
            pass

    exit_code = 1
    for cycle in range(1, max_cycles + 1):
        if stop["flag"]:
            log.info("[PROBE] nhận SIGINT/SIGTERM → dừng")
            exit_code = 130
            break
        try:
            account = await asyncio.wait_for(api.metatrader_account_api.get_account(account_id), timeout=60.0)
            ok = await run_cycle(api, account, symbol, throttle, trade_price, trade_enabled, state)
        except TooManyRequestsException as e:
            log.warning(f"[PROBE] 429 ở cấp account call → {await _wait_for_429(e):.0f}s rồi cycle kế tiếp")
            ok = False
        except asyncio.TimeoutError:
            log.warning(f"[PROBE] cycle {cycle}/{max_cycles}: REST/get_account timeout (cloud bận?)")
            ok = False
        except Exception as e:
            log.warning(f"[PROBE] cycle {cycle}/{max_cycles}: error {type(e).__name__}: {str(e)[:140]}")
            ok = False

        if ok:
            log.info(f"[PROBE] SUCCESS cycle {cycle}/{max_cycles} — pipeline THÔNG")
            exit_code = 0
            break
        if not stop["flag"]:
            delay = backoffs[min(cycle - 1, len(backoffs) - 1)]
            log.info(f"[PROBE] cycle {cycle}/{max_cycles} FAIL → backoff {delay}s (F5: retry chu kỳ)")
            await asyncio.sleep(delay)

    # F7: dọn dẹp ĐÚNG theo docs (close connections + close SDK)
    if state.get("stream") is not None:
        try:
            await state["stream"].close()
        except Exception:
            pass
    try:
        api.close()  # sync: "closes all clients and connections and stops all internal jobs"
    except Exception:
        pass
    return exit_code


if __name__ == "__main__":
    code = 0
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)
