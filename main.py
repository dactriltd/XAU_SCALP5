"""XAU_SCALP5 — entry point LIVE (demo).

ĐỘC LẬP HOÀN TOÀN với XAU_new: venv riêng · DB riêng (data/scalp5.db) · 0 import gói cũ.
SAFETY: HARD-STOP nếu account != demo · K=2 · LOT=0.02 · TP-only (không SL) · DAILY cap $30.

Chạy:  cd XAU_SCALP5 && SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem \
        nohup ./.venv/bin/python main.py >> logs/scalp5.out 2>&1 &
"""
import asyncio
import json
import logging
import os
import signal
import sqlite3
import time
from datetime import datetime, timezone

import aiosqlite
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))

from src import config as C
from src import lvl as _lvl          # S3-B: LVL M1 ladder (engine global)
from src.metaapi_client import MetaAPIClient
from src.models import Timeframe
from src.storage import get_storage
from src.tick_collector import TickCollector
from src.scalp_strategy import ScalpStrategy
from src.scalp_executor import ScalpExecutor

log = logging.getLogger("SCALP5")

DB_PATH = "data/scalp5.db"           # S3-B: DB dùng chung (replay riêng = URI ?mode=ro, bot LIVE = rw)

# S3-B V2: bảng M0 regime (DDL docs/DASHBOARD_DATA_SPEC.md §2.2 — trùng src/lvl.py DDL)
M0_SQL = """
CREATE TABLE IF NOT EXISTS regime_log (
  ts INTEGER NOT NULL,
  regime TEXT NOT NULL,            -- IMPULSE | V-REV | RANGE | CREEP
  regime_side TEXT NOT NULL DEFAULT '',   -- up | down | ''
  speed REAL, form_ratio REAL, extreme_age REAL,
  snap TEXT,                       -- JSON đầy đủ (debug)
  PRIMARY KEY (ts)
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_log(ts DESC);
"""

async def init_m0_tables() -> None:
    """S3-B: CREATE IF NOT EXISTS regime_log (additive — không đụng S2 paths)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(M0_SQL)
        await db.commit()


class StreamStalled(Exception):
    """Stream tick chết/hết (websocket MetaApi chết im lặng) → supervisor tự restart pipeline.
    Vị thế mở + TP broker-side được giữ (adopt lại khi restart)."""


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/scalp5.log"),
        ],
    )
    # 13-10 19:xx: socketio/engineio log mỗi keepalive/tick → scalp5.out phình 4.5GB/2h
    for noisy in ("metaapi_cloud_sdk", "aiosqlite", "httpx", "urllib3",
                  "socketio", "engineio", "websockets", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ─────────────────────────── telemetry (DB riêng) ───────────────────────────
TELEMETRY_SQL = """
CREATE TABLE IF NOT EXISTS entry_log (
    ts INTEGER, pos_id TEXT, kind TEXT, entry REAL, tp REAL, anchor REAL,
    touch INTEGER, drift5m REAL
);
CREATE TABLE IF NOT EXISTS exit_log (
    ts INTEGER, pos_id TEXT, reason TEXT, exit_px REAL, pnl REAL
);
"""

async def init_telemetry() -> None:
    async with aiosqlite.connect("data/scalp5.db") as db:
        await db.executescript(TELEMETRY_SQL)
        await db.commit()

async def tlog(kind: str, row: tuple) -> None:
    # S2: INSERT OR IGNORE — UNIQUE index (uq_exit_pos/uq_entry_pos) → idempotent:
    # CLOSE-FAIL retry loop / sync adopt-lại không thể ghi row trùng (row ts sớm nhất thắng)
    async with aiosqlite.connect("data/scalp5.db") as db:
        sql = f"INSERT OR IGNORE INTO {kind} VALUES ({','.join('?' * len(row))})"
        await db.execute(sql, row)
        await db.commit()


# ─────────────────────────── S2: boot backfill exit_log (chỉ chạy lúc boot) ─
def _deal_ts(d: dict):
    """Deal SDK shape camelCase (models.py MetatraderDeal): time=datetime|ISO-string."""
    t = d.get("time") or d.get("brokerTime")
    if t is None:
        return None
    if isinstance(t, datetime):
        return int(t.timestamp())
    try:
        return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


async def exit_action(a: dict, now: int, executor, tg, writer=tlog) -> None:
    """S2: khối EXIT — chỉ ghi exit_log khi close thật (ok=True).
    ok=False (pos vẫn ở broker mà close fail) → log warning + tg, KHÔNG tlog
    (vị thế vẫn được track → tick kế tiếp decide EXIT lại = retry, không spam row)."""
    pnl, ok = await executor.exit(a["pos_id"], a["px"], a["reason"])
    if ok:
        await writer("exit_log", (now, a["pos_id"], a["reason"], a["px"], pnl))
        # ── S4-HEDGE (15/10): sync hedge_credit THẬT từ broker + log phân nhánh D3 ──
        if a["reason"] == "HEDGE_TAKE":
            rid = str(a.get("parent_id") or "")
            root = next((p for p in executor.positions if p["id"] == rid), None)
            if root is not None:
                # pnl = lãi THỰC TẾ broker trả cho chân HEDGE (thay giá trị ước tính pts×2 của strategy)
                root["hedge_credit"] = float(pnl)
                log.info(f"[HEDGE] HEDGE_TAKE leg={a['pos_id']} pnl={pnl:+.2f}$ → root {rid} hedge_credit={root['hedge_credit']:+.2f}$ (BASKET_TP kế tiếp dùng giá trị này)")
            else:
                log.warning(f"[HEDGE] HEDGE_TAKE leg={a['pos_id']}: root {rid} không còn trong positions (đã đóng trước — bỏ qua credit sync)")
        if a["reason"] == "PRUNE_BREAK":
            # D3: 1 mã thoát PRUNE_BREAK cho cả 2 nhánh — log phân biệt (branch=LOCKED/UNWOUND)
            branch = a.get("branch", "LOCKED")
            log.info(f"[HEDGE] PRUNE_BREAK (branch={branch}) pos={a['pos_id']} pnl={pnl:+.2f}$ px={a['px']}")
        tg.send(f"📤 EXIT {a['reason']} @ {a['px']} · {pnl:+.2f}$")
        if executor.at_daily_cap:
            executor.halted = True
            tg.send(f"🛑 DAILY_LOSS_STOP {executor.day_loss:+.2f}$ → dừng entry hôm nay")
    else:
        log.warning(f"[EXEC] CLOSE_FAIL {a['pos_id']} {a['reason']} (close fail, pos vẫn ở broker → retry tick sau)")
        tg.send(f"🛑 CLOSE_FAIL {a['reason']} {a['pos_id']} (không ghi exit_log)")


async def boot_exit_log_sync(client, writer=tlog, db_path="data/scalp5.db") -> None:
    """S2: backfill exit_log cho position mà broker đã đóng (TP) nhưng bot chưa log
    (sync() branch (b) cũ không ai ghi exit_log → ~36 lệnh entry-mà-thiếu-exit).
    CALL LÚC BOOT THÔI (sau adopt()): window = ROL phiên hiện tại (21:45Z) → nay.
    INSERT OR IGNORE → mỗi pos_id tối đa 1 row; gọi thất bại RPC → log, KHÔNG crash boot."""
    now_ts = int(time.time())
    today_s = now_ts - now_ts % 86400
    rol_today = today_s + C.ROLLOVER_MIN
    # ROL trước đó: 21:45Z hôm nay nếu giờ đã qua ROL, còn không → 21:45Z hôm qua
    from_ts = rol_today if now_ts >= rol_today else rol_today - 86400
    try:
        deals = await client.get_history_deals(from_ts)  # wrapper int-sec → datetime UTC
    except Exception as e:
        log.warning(f"[BOOT-SYNC] get_deals_by_time_range fail ({type(e).__name__}: {e}) → skip backfill")
        return

    # nhóm theo positionId: open-deal (ts_open) + out-deal (exit px/pnl)
    groups: dict = {}
    for d in deals or []:
        if not isinstance(d, dict):
            continue
        mag = d.get("magic")
        if mag is not None and int(mag) != C.MAGIC:
            continue
        sym = d.get("symbol")
        if sym is not None and str(sym) != C.SYMBOL:
            continue
        pid = d.get("positionId")
        if not pid:
            continue
        et = str(d.get("entryType") or "").upper()
        g = groups.setdefault(str(pid), {"ts_open": None, "out_px": None, "out_pnl": None, "out_ts": None})
        ts = _deal_ts(d)
        if "IN" in et and g["ts_open"] is None:      # DEAL_ENTRY_IN / DEAL_ENTRY_INOUT
            g["ts_open"] = ts
        if "OUT" in et and g["out_ts"] is None:       # DEAL_ENTRY_OUT / OUT_BY / INOUT
            g["out_ts"] = ts
            g["out_px"] = d.get("price")
            g["out_pnl"] = d.get("profit")
    try:
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute("SELECT pos_id FROM exit_log")
            logged = {r[0] for r in await cur.fetchall()}
    except Exception as e:
        log.warning(f"[BOOT-SYNC] đọc exit_log fail ({type(e).__name__}: {e}) → skip")
        return
    n = 0
    for pid, g in groups.items():
        if g["out_ts"] is None or pid in logged:      # chưa đóng trong range / đã có row
            continue
        ts_open = g["ts_open"] if g["ts_open"] is not None else g["out_ts"]
        await writer("exit_log", (ts_open, pid, "EXIT_SYNC", g["out_px"], g["out_pnl"]))
        n += 1
    log.info(f"[BOOT-SYNC] backfill exit_log: {n}/{len(groups)} position đã đóng (from_ts={from_ts})")


# ─────────────────────────── telegram (optional) ───────────────────────────
class Tg:
    def __init__(self):
        self.n = None

    async def start(self) -> None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat or "your_" in token:
            log.info("[TG] không cấu hình → log-only")
            return
        try:
            from src.telegram import TelegramNotifier
            self.n = TelegramNotifier(token, chat, enable_commands=False)
            await self.n.start()
            log.info("[TG] connected")
        except Exception as e:
            log.warning(f"[TG] start failed ({e}) → log-only")

    def send(self, text: str) -> None:
        if self.n:
            self.n.enqueue(text)


# ─────────────────────────── main ───────────────────────────
def warn_token_expiry(token: str) -> None:
    """Giải mã JWT exp (không gọi mạng) → log cảnh báo hạn token.
    Lệnh 13/10/2026 (user): CHƯA đổi sang token console mới (hạn 11/11/2026),
    chỉ ghi cảnh báo. Xem TOKEN_WARNING.md. Hoạt động với bất kỳ token nào trong .env."""
    try:
        import base64
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        exp = int(json.loads(base64.urlsafe_b64decode(p))["exp"])
        days = (exp - time.time()) / 86400.0
        exp_iso = datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%d")
        if days <= 3:
            log.warning(f"[TOKEN] ⚠ METAAPI_TOKEN HẾT HẠN {'đã qua' if days < 0 else 'ngay'} ({exp_iso}, {days:.1f} ngày) → PHẢI regenerate token + cập nhật .env ngay")
        elif days <= 7:
            log.warning(f"[TOKEN] ⚠ METAAPI_TOKEN hết hạn {exp_iso} (còn {days:.1f} ngày) → chuẩn bị regenerate + cập nhật .env")
        else:
            log.info(f"[TOKEN] METAAPI_TOKEN hợp lệ đến {exp_iso} (còn {days:.0f} ngày)")
    except Exception as e:
        log.warning(f"[TOKEN] không giải mã được hạn token: {e}")


async def run() -> None:
    setup_logging()
    token = os.environ.get("METAAPI_TOKEN", "")
    account = os.environ.get("ACCOUNT_ID", "")
    if not token or "your_" in token or not account:
        raise SystemExit("[SAFETY] METAAPI_TOKEN/ACCOUNT_ID thiếu hoặc placeholder → không chạy")
    warn_token_expiry(token)

    client = MetaAPIClient(token, account)
    if not await client.initialize():
        raise SystemExit("[SAFETY] MetaApi initialize failed → không chạy")

    # ── HARD-STOP GATE: chỉ DEMO (MetaApi raw: type='ACCOUNT_TRADE_MODE_DEMO') ──
    # S4-BOOT (14/10 19:xx): RPC terminal data call HANG vô hạn khi cloud websocket MetaApi down
    # (proven probe 19:00: get_account_information >45s chưa return; boot 18:53 stuck đúng dòng này).
    # Bounded + fail-safe: RPC chưa xác nhận → demo_confirmed=False → NO-TRADE flag (chặn ENTER;
    # EXIT/data channels tiếp tục). Re-check 60s trong loop khi RPC recover. LIVE (confirmed
    # không-DEMO) → CHẶM như cũ (SystemExit(2)).
    demo_confirmed = False
    try:
        raw = await asyncio.wait_for(client.rpc_connection.get_account_information(), timeout=45.0)
    except Exception as e:
        log.warning(f"[SAFETY] RPC get_account_information fail/timeout ({type(e).__name__}) → NO-TRADE flag (re-check 60s trong loop khi RPC recover)")
    else:
        tmode = str(raw.get("type", "")).upper()
        if "DEMO" not in tmode:
            log.error(f"[SAFETY] trade-mode={raw.get('type')!r} server={raw.get('server')} → CHẶM (REFUSE LIVE)")
            raise SystemExit(2)
        demo_confirmed = True
        log.info(f"[SAFETY] DEMO OK · login={raw.get('login')} · server={raw.get('server')} · balance={raw.get('balance')} · lev={raw.get('leverage')}")

    storage = await get_storage("data/scalp5.db")
    await init_telemetry()

    strategy = ScalpStrategy(C)
    executor = ScalpExecutor(client, C)
    # ── ORDER BOOT 14/10 (USER): RPC warmup (initialize) → WS connect + PIPELINE CHECK → RPC historical (throttle) ──
    #   Tuần tự: kênh RPC warmup XONG (initialize phía trên) rồi mới mở kênh WS — một kênh
    #   một lúc, không song song. Pipeline check (streaming status + historical probe 5 nến)
    #   = "kiểm tra đường ống thông" TRƯỚC khi các fetch RPC historical nặng (throttle ≥5s).
    STATE_FILE = "data/state_snapshot.json"
    try:
        mw_ok = await asyncio.wait_for(client.ensure_market_watch([C.SYMBOL]), timeout=60.0)  # S4-BOOT: bounded (cloud down → ok=False, dung nạp)
    except Exception as e:
        mw_ok = False
        log.warning(f"[STREAM] ensure_market_watch timeout/fail ({type(e).__name__}) → pre-sync terminal")
    log.info(f"[STREAM] ensure_market_watch ok={mw_ok} → pre-sync terminal")
    strategy.now_ts = 0  # gate: chờ tick live đầu mới được decide() (px seed đã cũ)
    if not await client.start_streaming([C.SYMBOL]):
        # 13-10 22:xx — KHÔNG chết cứng: StreamStalled → main() retry backoff
        # (30s→60s→...→300s, vô hạn) cho đến khi terminal-state cloud sync được → LIVE.
        log.error(
            "[SAFETY] start_streaming FAIL (streaming sync kẹt phía cloud) → "
            "giữ process, tự retry theo backoff — vị thế + TP broker-side được giữ"
        )
        try:
            strategy.save_state(STATE_FILE)
            log.info("[STATE] snapshot saved (pre-StreamStalled)")
        except Exception as e:
            log.warning(f"[STATE] save (pre-StreamStalled) fail: {e}")
        # FIX WCH/H6: Đóng sạch WS (london:0/1) và RPC của chu kỳ hiện tại trước khi retry
        try:
            await client.shutdown()
            log.info("[STREAM] client.shutdown() hoàn tất trước khi retry StreamStalled")
        except Exception as e:
            log.warning(f"[STREAM] client.shutdown (pre-StreamStalled) fail: {e}")
        raise StreamStalled()
    log.info("[STREAM] stream_connection READY → pipeline check")
    await client.pipeline_check([C.SYMBOL])  # "đường ống thông?" (fail-open: warn only, không chặn boot)
    # S4-BOOT: bounded — RPC down thì adopt/boot_sync tự hoàn thành qua _reconnect_rpc cycle
    # (sync attempts 180s+60s → return (None, False) → positions=∅ / backfill skip);
    # 300s = cover trọn 1 cycle (không cancel giữa chừng)
    try:
        await asyncio.wait_for(executor.adopt(), timeout=300.0)
    except Exception as e:
        log.warning(f"[BOOT] adopt timeout/fail ({type(e).__name__}) → positions=∅ (broker flat verified user 14/10) · NO-TRADE giữ")
    try:
        await asyncio.wait_for(boot_exit_log_sync(client), timeout=300.0)  # S2: backfill exit_log (không crash nếu RPC fail)
    except Exception as e:
        log.warning(f"[BOOT] boot_exit_log_sync timeout/fail ({type(e).__name__}) → backfill skip (re-sync khi RPC recover)")
    # M2 (P2-H, HUMAN-approved 15/10): restore day$ từ exit_log (ngày UTC hiện tại) — counter RAM
    # reset 0.0 mỗi lần restart pipeline (StreamStalled backoff / process) → fuse DAILY_LOSS_STOP
    # ($30) bị vô hiệu sau nhiều lần cloud-flap (evidence: 01:40/02:50/05:01 day$ +3.72→0.00).
    # Read-only; boundary = đầu ngày UTC (khớp rollover ordinal của note_closed). Fail → giữ 0.0.
    try:
        _day_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        async with aiosqlite.connect(DB_PATH) as db:
            _cur = await db.execute(
                "SELECT COALESCE(SUM(pnl), 0.0), COUNT(*) FROM exit_log WHERE ts >= ?", (_day_start,))
            _s, _n = await _cur.fetchone()
        executor.day_utc = datetime.now(timezone.utc).toordinal()
        executor.day_loss = float(_s or 0.0)
        log.info(f"[BOOT] day$ restored {executor.day_loss:+.2f} ({_n} exits, UTC-day ≥ {_day_start})")
    except Exception as e:
        log.warning(f"[BOOT] day$ restore fail ({type(e).__name__}) → giữ 0.0 (fuse reset như cũ)")
    if executor.at_daily_cap:
        executor.halted = True

    # ── S3-B V2: M0 regime_log DDL + LVL engine BOOT rebuild (best-effort: fail KHÔNG crash boot) ──
    #   fail → G2-LVL/EXT15 + R1/R2 auto-disable (lvl._engine None → strategy fail-open),
    #   on_m1_close tick sau tự tạo engine (lvl.on_m1_close) → V2 sống lại không cần restart.
    try:
        await init_m0_tables()
        log.info("[V2] regime_log DDL ok (§2.2)")
    except Exception as e:
        log.warning(f"[V2] init_m0_tables fail (regime_log sẽ không ghi): {type(e).__name__}: {e}")
    try:
        # FIX LVL-THREADING: conn sqlite3 ĐỒNG BỘ riêng (WAL → không xung đột pool aiosqlite)
        # (conn của worker-thread aiosqlite dùng cross-thread → ProgrammingError "created in a thread")
        with sqlite3.connect(DB_PATH) as sync_conn:
            _lvl.rebuild_from_candles(sync_conn, C.SYMBOL)
            sync_conn.commit()
        log.info(f"[V2] LVL engine rebuilt: {len(_lvl._engine.zones) if _lvl._engine else 0} zones m1")
    except Exception as e:
        log.warning(f"[V2] LVL rebuild fail (G2/R1R2 tạm disable, tự hồi khi on_m1_close): {type(e).__name__}: {e}")

    # ── WARMUP: nến lịch sử TRONG NGÀY → S-ladder (M5/M1 theo LADDER_TF) + drift M1 (KHÔNG hindsight: bỏ nến đang form) ──
    # ── STATE SNAPSHOT (14-10): restore cascade (ladder/touches/fz/arm) từ JSON nếu fresh (<4h) ──
    _state_loaded = False  # STATE_FILE: đã khai báo trong block ORDER BOOT (~L273)
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as _sf:
                _snap = json.load(_sf)
            _age_h = (time.time() - _snap.get("ts", 0)) / 3600
            if _age_h < 4 and strategy.load_state(_snap):
                _state_loaded = True
                log.info(f"[STATE] snapshot restored ({_age_h:.1f}h cũ) → skip WARMUP seed")
            else:
                log.info(f"[STATE] snapshot không dùng (tuổi={_age_h:.1f}h ≥4h hoặc rỗng) → WARMUP seed")
    except Exception as e:
        log.warning(f"[STATE] snapshot load fail ({type(e).__name__}: {e}) → WARMUP seed")

    # ── S4-HEDGE: re-attach rổ metadata vào adopted positions (sau StreamStalled restart) ──
    # adopt() recover vị thế broker MỘC (không có parent_id/leg_type/hedge_credit/…) → restore từ
    # strategy.hedge_baskets (state_snapshot.json, mirror của strategy.decide()). Rổ LOCKED/UNWOUND
    # tiếp tục chạy đúng state; mirror stale (root đã đóng) tự prune tại decide() tick kế tiếp.
    if getattr(C, "HEDGE_ENABLE", False) and strategy.hedge_baskets:
        by_id = {q["id"]: q for q in executor.positions}
        n_attached = 0
        for rid, rec in strategy.hedge_baskets.items():
            root = by_id.get(rid)
            if root is not None:
                root.setdefault("wall_px", rec.get("wall_px"))
                root.setdefault("wall_peak_px", rec.get("wall_peak_px"))
                root.setdefault("unwound", bool(rec.get("unwound", False)))
                root.setdefault("hedge_credit", float(rec.get("hedge_credit", 0.0)))
                root.setdefault("net_peak_usd", float(rec.get("net_peak_usd", 0.0)))
                n_attached += 1
            for lid in rec.get("leg_ids", []):
                legp = by_id.get(lid)
                if legp is not None:
                    legp["parent_id"] = rid
                    legp["leg_type"] = "HEDGE"
                    legp.setdefault("hedge_credit", 0.0)
                    legp.setdefault("unwound", False)
                    legp.setdefault("wall_px", rec.get("wall_px"))
                    n_attached += 1
        log.info(f"[HEDGE] re-attach rổ metadata: {n_attached} position (registry {len(strategy.hedge_baskets)} rổ)")

    # ── GAP CHECK (14-10): nến M1 đã trong DB → chỉ fetch phần thiếu từ MetaApi ──
    try:
        from src.gap_filler import M1GapFiller
        _filler = M1GapFiller(client, storage)
        _n_gaps = await _filler.find_m1_gaps(1)
        if _n_gaps:
            _filled = await _filler.fill_all_gaps(lookback_days=1, max_total_candles=2000)
            log.info(f"[GAP] {len(_n_gaps)} gap (1 ngày) → filled={_filled} nến M1 từ MetaApi")
        else:
            log.info("[GAP] DB nến M1 đủ (1 ngày) — không fetch")
    except Exception as e:
        log.warning(f"[GAP] gap-check fail (không chặn boot): {type(e).__name__}: {e}")

    now_ts = int(time.time())
    today_start = now_ts - (now_ts % 86400)
    m1_closed_cut = now_ts - now_ts % 60
    n_seed = 0
    seed_desc = "skip (state snapshot restored)"
    if _state_loaded:
        log.info("[STATE] WARMUP skip — ladder/fz/arm/touches restore từ snapshot (positions unchanged)")
    elif C.LADDER_TF == "M1":
        # H4 (DB-first warmup): lấy nến từ DB trước, chỉ gọi RPC khi DB thiếu dữ liệu
        m1 = await storage.get_candles(C.SYMBOL, Timeframe.M1, C.S1_SWINGS)
        if not m1 or len(m1) < 30:
            m1 = await client.fetch_candles(C.SYMBOL, Timeframe.M1, limit=C.S1_SWINGS)
        m1_today = [(int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close)
                    for c in m1 if today_start <= int(c.timestamp.timestamp()) < m1_closed_cut]
        n_seed = strategy.seed_m1_bars(m1_today)
        seed_desc = f"M1 trong ngày (khép)={len(m1_today)} nến"
    else:
        m5_closed_cut = now_ts - now_ts % 300
        m5 = await client.fetch_candles(C.SYMBOL, Timeframe.M5, limit=240)
        m5_today = [(int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close)
                    for c in m5
                    if today_start <= int(c.timestamp.timestamp()) < m5_closed_cut]
        strategy.seed_m5(m5_today)
        m1 = await client.fetch_candles(C.SYMBOL, Timeframe.M1, limit=35)
        m1_ok = [(int(c.timestamp.timestamp()), c.close)
                 for c in m1 if int(c.timestamp.timestamp()) < m1_closed_cut]
        n_seed = strategy.seed_m1(m1_ok)
        seed_desc = f"M5 trong ngày (khép)={len(m5_today)} nến · M1 closes={len(m1_ok)}"
    alive_lv = [lv for lv in strategy.levels if not lv.broken]
    log.info(
        f"[WARMUP] {seed_desc} · L={n_seed} tick-seed · ladder={C.LADDER_TF} · bounce={C.S_BOUNCE_PTS} · "
        f"L-alive={[round(lv.px, 1) for lv in alive_lv if lv.kind == 'L'][-6:]} · "
        f"H-alive={[round(lv.px, 1) for lv in alive_lv if lv.kind == 'H'][-6:]} · "
        f"drift5m={strategy.drift5m():+.2f}"
    )

    # (ORDER BOOT 14/10: STREAMING block đã chuyển LÊN TRƯỚC adopt/backfill/gap-fill —
    #  RPC warmup → WS + pipeline check → RPC historical reads throttle ≥5s. Xem run() ~L269.)

    tg = Tg()
    await tg.start()

    async def _m1_close_hook(cts: int, o: float, h: float, l: float, cpx: float) -> None:
        """S3-B V2 m1-CLOSE hook (additive — S2 paths giữ nguyên): LVL engine advance + persist,
        M0 regime tag (m1 proxy) + regime_log (chỉ khi tag đổi · DDL §2.2 · tlog INSERT OR IGNORE),
        R1/R2 arm scan (M0-gated; FILL tick-level trong strategy.decide)."""
        # 1) LVL engine (global): nến vừa khép → advance + UPSERT bảng lvl (best-effort)
        try:
            # FIX LVL-THREADING: conn sqlite3 đồng bộ (best-effort, mỗi nến M1 khép)
            with sqlite3.connect(DB_PATH) as sync_conn:
                _lvl.on_m1_close(sync_conn, cts, (o, h, l, cpx))
                sync_conn.commit()
        except Exception as e:
            log.warning(f"[LVL] on_m1_close fail (engine in-memory tiếp tục): {type(e).__name__}: {e}")
        # 2) M0 regime (tag m1-proxy) + regime_log khi tag đổi
        try:
            regime, snap = strategy.m0_on_m1_close(cts, o, h, l, cpx)
            if snap is not None:
                await tlog("regime_log", (cts, snap["tag"], snap["side"], snap["speed"], snap["form"],
                                           snap["age"], json.dumps(snap)))
                log.info(f"[M0] regime → {regime} (speed={snap['speed']} form={snap['form']} "
                         f"age={snap['age']} fz={snap['fz_touches']})")
        except Exception as e:
            log.warning(f"[M0] m0_on_m1_close fail (không arm R1/R2 nến này): {type(e).__name__}: {e}")
        # 3) R1/R2 STALL-FADE arm scan (chỉ log; fill tại decide())
        try:
            new_arms = strategy.r1r2_arm_scan(len(executor.positions))
            for a in new_arms:
                log.info(f"[V2] R-arm {a['key'][0]}-zone {a['lvl_px']:.2f} (touches={a.get('touches', 0)}) "
                         f"→ {a['side']}-LIMIT @ {a['px']:.2f} · regime={a['regime']} · TTL {C.LIMIT_TTL}'")
        except Exception as e:
            log.warning(f"[V2] r1r2_arm_scan fail: {type(e).__name__}: {e}")

    _m1bar = [0, None]  # S3-B: [phút_m1, [o, h, l, c] nến đang form] — main tự track OHLC (strategy không có open)

    async def on_tick(tick) -> None:  # collector await callback (line 212 tick_collector)
        ts = int(tick.timestamp.timestamp())
        px = float(tick.bid)
        m1_ts = ts - ts % 60
        if _m1bar[1] is not None and m1_ts != _m1bar[0]:
            cts, o, h, l, cpx = _m1bar[0], *_m1bar[1]
            await _m1_close_hook(cts, o, h, l, cpx)      # S3-B: m1 close → LVL + M0 + R1/R2
        if _m1bar[1] is None or m1_ts != _m1bar[0]:
            _m1bar[0], _m1bar[1] = m1_ts, [px, px, px, px]
        else:
            _m1bar[1][1] = max(_m1bar[1][1], px)
            _m1bar[1][2] = min(_m1bar[1][2], px)
            _m1bar[1][3] = px
        strategy.on_tick(ts, px)

    collector = TickCollector(client, [C.SYMBOL], storage, on_tick_callback=on_tick)
    await collector.start()
    wins = ((0, C.ROLLOVER_MIN),) if C.WINDOWS_ALL else C.WINDOWS
    log.info(
        f"[SCALP5] LIVE START · {C.SYMBOL} · MODE={C.MODE} · TP={C.TP_POINTS}pts · LOT={C.LOT} · K={C.K_CONTEXT} · "
        f"windows {wins} · ROL {C.ROLLOVER_MIN//60}:{C.ROLLOVER_MIN%60:02d}Z"
    )
    tg.send(f"✅ SCALP5 LIVE START (demo) · MODE {C.MODE} · {C.SYMBOL} · TP {C.TP_POINTS}pts · lot {C.LOT}")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    last_hb = 0.0
    last_nt = 0.0  # S4-BOOT: dedup log NO-TRADE (≥300s/lần)
    watch_base = int(time.time())  # baseline watchdog: loop bắt đầu (chưa có tick) → tick đầu tiên → tick cuối
    stale_exit = False

    # S4-BOOT: DEMO gate chưa confirm (RPC down lúc boot) → re-check mỗi 60s; detect LIVE → stop loop
    if not demo_confirmed:
        async def _demo_recheck() -> None:
            nonlocal demo_confirmed
            while not demo_confirmed and not stop.is_set():
                await asyncio.sleep(60)
                try:
                    raw2 = await asyncio.wait_for(client.rpc_connection.get_account_information(), timeout=20.0)
                except Exception:
                    continue
                tmode2 = str(raw2.get("type", "")).upper()
                if "DEMO" in tmode2:
                    demo_confirmed = True
                    log.info(f"[SAFETY] DEMO re-confirmed (RPC recover) · login={raw2.get('login')} · server={raw2.get('server')} → trading ENABLE")
                    tg.send("✅ SCALP5 DEMO re-confirmed (RPC recover) → trading ENABLE")
                else:
                    log.critical(f"[SAFETY] re-check trade-mode={raw2.get('type')!r} KHÔNG-DEMO → CHẶM loop (REFUSE LIVE, không auto-restart)")
                    tg.send("🛑 SCALP5 CHẶM: re-check trade-mode KHÔNG-DEMO (REFUSE LIVE)")
                    stop.set()
        asyncio.create_task(_demo_recheck())
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            break
        if strategy.now_ts:
            watch_base = strategy.now_ts

        # WATCHDOG (13-10 17:xx): websocket MetaApi chết im lặng → tick STALE
        # (sự cố thật: 2 lần chết 16:48/16:52, tick đóng băng 55′, bot không có lệnh).
        # Mon-Fri UTC; market đóng cuối tuần → không trigger vô ích.
        if time.time() - watch_base > C.TICK_STALE_SECONDS and datetime.now(timezone.utc).weekday() < 5:
            stale_exit = True
            log.critical(
                f"[STREAM] TICK STALE >{C.TICK_STALE_SECONDS}s (last-tick {watch_base} → now {int(time.time())}) · "
                f"WebSocket chết im lặng → force-restart pipeline (giữ vị thế + TP ở broker)"
            )
            break

        if not strategy.now_ts:
            continue
        now = strategy.now_ts

        # heartbeat + status mỗi 5'
        if now - last_hb >= 300:
            last_hb = now
            alive = [lv for lv in strategy.levels if not lv.broken]
            status = {
                "ts": now,
                "px": strategy.last_px,
                "drift5m": round(strategy.drift5m(), 2),
                "mode": strategy.mode(),
                "L": [[lv.px, lv.touches, lv.confirmed] for lv in alive if lv.kind == "L"][-8:],
                "H": [[lv.px, lv.touches, lv.confirmed] for lv in alive if lv.kind == "H"][-8:],
                "open": executor.positions,
                "day_loss": round(executor.day_loss, 2),
                "halted": executor.halted,
            }
            with open("logs/scalp5.status.json", "w") as f:
                json.dump(status, f, indent=1)
            try:
                strategy.save_state(STATE_FILE)
            except Exception as e:
                log.warning(f"[STATE] save (HB 5') fail: {e}")
            log.info(
                f"[HB] px={strategy.last_px} d5m={strategy.drift5m():+.2f} mode={strategy.mode()} "
                f"L={len(status['L'])} H={len(status['H'])} open={len(executor.positions)} day$={executor.day_loss:+.2f}"
            )

        # ── decide + execute ──
        actions = strategy.decide(executor.positions, wins, C.ROLLOVER_MIN)
        for a in actions:
            if a["kind"] in ("ENTER_LONG", "ENTER_SHORT"):
                if not demo_confirmed:
                    if now - last_nt >= 300:
                        last_nt = now
                        log.warning(f"[SAFETY] ENTER skip ({a['kind']}) — DEMO chưa confirm (RPC down) · NO-TRADE flag ON (log 300s/lần)")
                    continue
                ok = await executor.enter(a, strategy)
                if ok:
                    p = executor.positions[-1]
                    if a.get("arm"):
                        p["r1r2"] = True   # S3-B: R1/R2 entry → exit 4-lớp (TP/PSL/ROL/DRIFT-FLIP, KHÔNG TIME)
                    side = 1 if a["kind"] == "ENTER_LONG" else -1
                    if a.get("leg_type") == "HEDGE":
                        # S4-HEDGE: chân HEDGE không có TP trên sàn (tp=NULL) — tlog giữ semantics (TP=rỗng)
                        await tlog("entry_log", (
                            now, p["id"], a["kind"], p["entry"],
                            None, a.get("anchor"),
                            a.get("touch", 0), a.get("drift5m", 0.0),
                        ))
                        tg.send(f"🛡 HEDGE {a['kind']} @ {p['entry']} (root {a.get('parent_id')} · cản {a.get('anchor')} · KHÔNG-TP)")
                    else:
                        await tlog("entry_log", (
                            now, p["id"], a["kind"], p["entry"],
                            p["entry"] + side * C.TP_POINTS, a.get("anchor"),
                            a.get("touch"), a.get("drift5m"),
                        ))
                        tg.send(f"📥 {a['kind']} @ {p['entry']} · TP {p['entry'] + side * C.TP_POINTS} · S={a.get('anchor')}")
            elif a["kind"] == "EXIT":
                await exit_action(a, now, executor, tg)  # S2: chỉ tlog khi close ok

        # ratchet MOM1 (CHAIRMAN 19:xx): điều chỉnh TP broker theo đỉnh lãi (lệnh chạy cùng giá)
        await executor.apply_tp_updates(strategy.tp_plan(executor.positions))

        # đối soát TP-fill bên broker
        await executor.sync()
        # S2: vị thế sync() phát hiện broker-đã-đóng (TP fill) → ghi exit_log (INSERT OR IGNORE,
        # row ts sớm nhất thắng) + thông báo tg; list clear sau khi xử lý
        if executor.synced_exits:
            for sx in executor.synced_exits:
                await tlog("exit_log", (sx["ts"], sx["pos_id"], "EXIT_SYNC", None, sx["pnl_est"]))
                tg.send(f"📤 EXIT_SYNC {sx['pos_id']} ≈{sx['pnl_est']:+.2f}$")
            executor.synced_exits.clear()

    # ── shutdown: giữ vị thế (TP còn ở broker), tắt stream + RPC sạch ──
    log.info("[SCALP5] shutdown → stop collector + client.shutdown (vị thế mở vẫn giữ TP ở broker)")
    try:
        strategy.save_state(STATE_FILE)
        log.info("[STATE] snapshot saved (shutdown)")
    except Exception as e:
        log.warning(f"[STATE] save (shutdown) fail: {e}")
    try:
        await collector.stop()
        await client.shutdown()
    except Exception as e:
        log.warning(f"[SCALP5] shutdown error (không chặn exit): {e}")

    if stale_exit:
        raise StreamStalled()


PID_FILE = "logs/scalp5.pid"

def write_pid() -> None:
    os.makedirs("logs", exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def main() -> None:
    write_pid()
    try:
        while True:
            try:
                asyncio.run(run())
                return  # clean exit (SIGINT/SIGTERM) → dừng hẳn
            except StreamStalled:
                now = time.time()
                backoff = 30 if not hasattr(main, "_last_fail") or now - main._last_fail > 900 else min(main._backoff * 2, 300)
                main._backoff = backoff
                main._last_fail = now
                log.warning(f"[SCALP5] STREAM STALLED → tự khởi động lại pipeline trong {backoff}s (vị thế + TP broker-side được giữ, adopt lại khi lên)")
                time.sleep(backoff)
            except SystemExit as e:
                log.error(f"[SCALP5] EXIT: {e}")
                raise
            except KeyboardInterrupt:
                return
    finally:
        remove_pid()


if __name__ == "__main__":
    main()
