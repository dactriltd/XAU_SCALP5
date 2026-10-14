#!/usr/bin/env python3
"""XAU_SCALP5 — 5-MINUTE VERIFICATION LOOP (Karpathy Law 1: minimal, Law 3: empirical).

Đọc 3 nguồn:
  1. logs/scalp5.status.json  — heartbeat mỗi 5 min của main.py
  2. data/scalp5.db           — SQLite telemetry (entry_log, exit_log)
  3. logs/scalp5.log          — 50 dòng cuối (StreamStalled, watchdog events)
  4. logs/scalp5.pid          — PID process bot (liveness check)

Kết quả: logs/scalp5_verify_report.json + exit code
  0 = PASS   (tất cả blocks OK)
  1 = WARN   (có block cảnh báo, không cần can thiệp ngay)
  2 = FAIL   (block nghiêm trọng, cần kiểm tra thủ công / restart)

Chạy:
  --once  : chạy 1 lần rồi exit (cho cron)
  --loop  : chạy liên tục mỗi 5 min (cho nohup)

Karpathy Law 1 (Minimal): 0 dependency ngoài stdlib.
Karpathy Law 9 (Baseline): thresholds lấy từ config.py + data thực tế.
"""
import json
import os
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─────────────────────────── PATHS ───────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
STATUS     = BASE_DIR / "logs" / "scalp5.status.json"
DB         = BASE_DIR / "data" / "scalp5.db"
LOG        = BASE_DIR / "logs" / "scalp5.log"
PID_FILE   = BASE_DIR / "logs" / "scalp5.pid"
REPORT     = BASE_DIR / "logs" / "scalp5_verify_report.json"
VERIFY_LOG = BASE_DIR / "logs" / "scalp5_verify.log"

# ─────────────────────────── THRESHOLDS (Karpathy Law 9: baseline) ───────────────────────────
# Lấy giá trị từ src/config.py — verify loop chỉ đọc file, không import src (bẩn)
TICK_STALE_FAIL_S  = 300    # = config.TICK_STALE_SECONDS (TICK STALE → StreamStalled)
TICK_STALE_WARN_S  = 120    # WARN early (2 min không tick = đáng lo)
DRIFT_WARN_PX      = 20.0   # |drift5m| > $20 = extreme (XAUUSDm session range)
K_CONTEXT_MAX      = 4      # = config.K_CONTEXT
DAILY_LOSS_CAP     = -30.0  # = config.DAILY_LOSS_STOP
NO_TELEMETRY_S     = 3600   # > 1h không có entry/exit = WARN (bot idle?)
STALL_FAIL_N       = 3      # ≥ 3× STREAM STALLED trong session = FAIL
PID_CHECK_TIMEOUT  = 0.5
# BLOCK 6 thresholds (entry quality)
WIN_RATE_WARN      = 0.40  # win rate < 40% (trên exits rõ) = WARN
STREAK_LOSS_FAIL   = 3     # ≥ 3 lệnh lỗ liên tiếp = FAIL
TP_RATE_FAIL       = 0.25  # TP rate < 25% (trên exits) = FAIL (strategy kém timing)
# BLOCK 7 thresholds (structure)
FZ_MIN_TOUCH       = 2     # = config.FZ_MIN_TOUCH (strong zone = tested ≥ 2 lần)
FZ_BAND_PTS        = 0.5   # = config.FZ_BAND_PTS (±0.5pts = "at the zone")
TIGHT_BOX_PTS      = 2.0   # box range < 2.0pts = range-bound, MOM1 yếu

# ─────────────────────────── DATA CLASSES ───────────────────────────
@dataclass
class CheckResult:
    """1 block = 1 câu hỏi 5W2H + bằng chứng Karpathy Law 3 + 5 Whys trace."""
    block: str
    what: str                 # 5W2H What: điều gì đang được kiểm tra
    observed: Any             # Karpathy Law 3: giá trị thực (concrete)
    status: str              # "PASS" | "WARN" | "FAIL"
    evidence: str            # Nguồn data (file/line)
    whys: List[str] = field(default_factory=list)   # 5 Whys trace
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Remove empty lists to keep JSON clean
        if not d.get("whys"):
            d.pop("whys")
        if not d.get("detail"):
            d.pop("detail")
        return d


# ─────────────────────────── LOADERS ───────────────────────────
def load_status() -> Dict:
    """Đọc status.json heartbeat (viết mỗi 5 min bởi main.py)."""
    if not STATUS.exists():
        return {}
    try:
        with open(STATUS) as f:
            return json.load(f)
    except Exception:
        return {}


def load_db_metrics() -> Dict:
    """Query telemetry DB (entry_log + exit_log)."""
    if not DB.exists():
        return {}
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        cur = conn.cursor()
        now_ts = int(time.time())
        day_start = now_ts - (now_ts % 86400)

        cur.execute(
            "SELECT COUNT(*), MAX(ts), COALESCE(SUM(CASE WHEN ts > ? THEN pnl ELSE 0 END), 0) "
            "FROM exit_log WHERE ts > ?", (day_start, day_start)
        )
        row = cur.fetchone()
        n_today, last_ts, pnl_today = (row[0] or 0), row[1], row[2]

        cur.execute(
            "SELECT COUNT(*), MAX(ts) FROM entry_log WHERE ts > ?", (day_start,)
        )
        row2 = cur.fetchone()
        n_entries_today, last_entry_ts = (row2[0] or 0), row2[1]

        conn.close()
        return {
            "n_exits_today": int(n_today),
            "pnl_today": float(pnl_today or 0),
            "last_exit_ts": last_ts,
            "n_entries_today": int(n_entries_today),
            "last_entry_ts": last_entry_ts,
            "day_start": day_start,
        }
    except Exception:
        return {}


def load_entry_quality_metrics() -> Dict:
    """BLOCK 6 data: JOIN entry_log + exit_log hôm nay.

    Lưu ý: TP-broker exits không có trong exit_log (chỉ note_closed → day_loss).
    → exit_log = bot-initiated exits (TIME, ROL, S_BREAK, FADE, TRAIL, TP).
    → total_entries - total_closed_in_db = TP-broker exits (estimate PnL = +$3.04/đơn).
    """
    if not DB.exists():
        return {}
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        cur = conn.cursor()
        now_ts = int(time.time())
        day_start = now_ts - (now_ts % 86400)

        # All entries today
        cur.execute(
            "SELECT kind, entry, drift5m, tp, anchor, touch FROM entry_log WHERE ts >= ? ORDER BY ts",
            (day_start,))
        entries = cur.fetchall()

        # All exits today (bot-initiated only)
        cur.execute(
            "SELECT pos_id, reason, pnl FROM exit_log WHERE ts >= ? ORDER BY ts",
            (day_start,))
        exits = cur.fetchall()

        # PnL by reason
        cur.execute(
            "SELECT reason, COUNT(*), AVG(pnl), MIN(pnl) FROM exit_log WHERE ts >= ? GROUP BY reason",
            (day_start,))
        reason_dist = {r[0]: {"n": r[1], "avg_pnl": r[2] or 0, "min_pnl": r[3] or 0}
                       for r in cur.fetchall()}

        conn.close()

        # Metrics
        total_entries = len(entries)
        total_closed_db = len(exits)
        wins = sum(1 for x in exits if (x[2] or 0) > 0)
        losses = sum(1 for x in exits if (x[2] or 0) < 0)
        win_rate = wins / total_closed_db if total_closed_db else 0.0

        # PnL total (DB only — exclude TP-broker estimate to keep empirical)
        total_pnl_db = sum(x[2] or 0 for x in exits)

        # TP rate: TP exits / total exits in DB
        n_tp = reason_dist.get("TP", {}).get("n", 0)
        tp_rate = n_tp / total_closed_db if total_closed_db else 0.0
        time_rate = reason_dist.get("TIME", {}).get("n", 0) / total_closed_db if total_closed_db else 0.0

        # Drift alignment: against-momentum entry = better (buy dip / sell rally)
        against = 0
        with_mom  = 0
        for e in entries:
            kind, drift = e[0], e[2] or 0
            if kind == "ENTER_LONG"  and drift < 0: against += 1
            elif kind == "ENTER_SHORT" and drift > 0: against += 1
            elif kind == "ENTER_LONG"  and drift >= 0: with_mom += 1
            elif kind == "ENTER_SHORT" and drift <= 0: with_mom += 1
        # Store as fraction (0.0–1.0) → f-string ":{:.0%}" multiplies by 100
        against_frac = against / total_entries if total_entries else 0.0

        # Loss streak (consecutive, most recent exits)
        streak_loss = 0
        for x in reversed(exits):
            if (x[2] or 0) < 0:
                streak_loss += 1
            else:
                break

        return {
            "total_entries":   total_entries,
            "total_closed_db": total_closed_db,
            "n_tp_broker_est": total_entries - total_closed_db,  # ước tính (không empirical)
            "wins":            wins,
            "losses":          losses,
            "win_rate":        win_rate,
            "total_pnl_db":    total_pnl_db,
            "avg_pnl_closed":  (total_pnl_db / total_closed_db) if total_closed_db else 0.0,
            "tp_rate":         tp_rate,
            "time_rate":       time_rate,
            "against_frac":    against_frac,
            "streak_loss":     streak_loss,
            "reason_dist":     reason_dist,
        }

    except Exception:
        return {}


def read_log_tail(n_lines: int = 50) -> str:
    """Đọc n dòng cuối của scalp5.log (không load cả file ~20MB)."""
    if not LOG.exists():
        return ""
    try:
        lines: List[str] = []
        with open(LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = 8192
            pos = size
            data = b""
            while pos > 0 and len(lines) < n_lines:
                read = min(block, pos)
                pos -= read
                f.seek(pos)
                data = f.read() + data
                data_lines = data.decode("utf-8", errors="replace").splitlines()
                lines = data_lines[-(n_lines - len(lines)):] + lines
                if pos == 0:
                    break
        return "\n".join("\n".join(lines[-n_lines:]).splitlines()[-n_lines:])
    except Exception:
        return ""


def is_pid_alive(pid_str: str) -> bool:
    """Kiểm tra PID còn sống không (kill -0 equivalent, cross-platform)."""
    try:
        pid = int(pid_str.strip())
        os.kill(pid, 0)  # SIG 0 = check existence, không gửi signal
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except (ValueError, OSError):
        return False


# ─────────────────────────── CHECKS ───────────────────────────

def check_tick_stream(status: Dict) -> CheckResult:
    """BLOCK 1: TICK STREAM (I/O layer).
    5W2H What: tick freshness
    5W2H Why:  tick chết → strategy.now_ts stale → decide() gate → bot idle
    5W2H How:  now - status.json.ts
    5W2H HowMuch: FAIL > 300s, WARN > 120s
    """
    now = int(time.time())
    ts  = status.get("ts", 0)
    px  = status.get("px", None)

    if ts == 0 or px is None:
        # status.json rỗng → main.py heartbeat chưa chạy / bot chưa có tick
        st = "FAIL"
        observed = f"status.json ts={ts} px={px} (empty/absent)"
        whys = [
            "1. Why status.json empty? → main.py heartbeat chưa viết (bot chưa chạy / crash)",
            "2. Why heartbeat chưa viết? → strategy.now_ts = 0 (chưa có tick live)",
            "3. Why no tick? → stream_connection chưa READY / subscribe fail",
            "4. Why subscribe fail? → MetaAPI cloud gateway stuck-sync (synchronizationStatus=None)",
            "5. ROOT: check log có 'stream_connection READY' không; nếu không → redeploy terminal (escalation)",
        ]
    else:
        age = now - ts
        if age > TICK_STALE_FAIL_S:
            st = "FAIL"
        elif age > TICK_STALE_WARN_S:
            st = "WARN"
        else:
            st = "PASS"
        observed = f"age={age}s (ts={ts}, px={px})"
        whys = [
            f"1. Why tick age={age}s? → WebSocket không delivery / collector không callback",
            "2. Why collector stopped? → stream_connection dead (MetaAPI WS silent)",
            "3. Why WS dead? → MetaAPI cloud gateway timeout / no keepalive",
            "4. Why no keepalive? → SDK limitation (MetaApi server-side sync, không expose keepalive API)",
            "5. ROOT: TICK_STALE_SECONDS watchdog (main.py) + StreamStalled backoff (30→300s) — check log có 'STREAM STALLED'",
        ]

    return CheckResult(
        block="1_TICK_STREAM",
        what=f"Tick freshness: now-status.ts",
        observed=observed,
        status=st,
        evidence=f"logs/scalp5.status.json → ts={ts}, px={px}",
        whys=whys,
        detail={"ts": ts, "px": px, "now": now, "age_s": now - ts if ts else None},
    )


def check_strategy_state(status: Dict) -> CheckResult:
    """BLOCK 2: STRATEGY STATE (CPU layer).
    5W2H What: drift5m, S-ladder levels, mode
    5W2H Why:  strategy state drift → quyết định entry/exit sai
    5W2H How:  đọc drift5m, L[], H[] từ status.json
    5W2H HowMuch: |drift| > 20 = WARN, L+H=0 = WARN
    """
    drift  = status.get("drift5m", 0) or 0
    mode   = status.get("mode", None)
    l_arr  = status.get("L", [])
    h_arr  = status.get("H", [])
    n_l, n_h = len(l_arr), len(h_arr)

    issues: List[str] = []
    if abs(drift) > DRIFT_WARN_PX:
        issues.append(f"|drift5m|={drift:+.1f} > ${DRIFT_WARN_PX} (extreme)")
    if n_l == 0 and n_h == 0:
        issues.append("S-ladder rỗng (L=0 H=0) — B_SNEO không có trigger, MOM1 vẫn chạy")

    st = "WARN" if issues else "PASS"
    observed = f"drift5m={drift:+.2f} mode={mode} L={n_l} H={n_h}"

    whys = [
        f"1. Why drift={drift:+.2f}? → px_now vs M1[-5] close — trend mạnh (news/session shift)",
        "2. Why S-ladder rỗng? → Tất cả level broken (trend xuyên) hoặc chưa warmup đủ",
        "3. Why level broken? → Price > S_CHAIN_BREAK ($0.1 M1) qua tất cả H/L",
        "4. Why warmup thiếu? → Bot start giữa phiên → seed_m1_bars chỉ có N nến",
        "5. ROOT: check [WARMUP] log — n_seed=0 → seed fail (broker không trả candle)",
    ]

    return CheckResult(
        block="2_STRATEGY_STATE",
        what=f"drift5m, S-ladder, mode validity",
        observed=observed,
        status=st,
        evidence=f"status.json → drift5m={drift}, mode={mode}, L={n_l}, H={n_h}",
        whys=whys,
        detail={
            "drift5m": drift, "mode": mode,
            "n_l": n_l, "n_h": n_h,
            "l_levels": [x[0] for x in l_arr],
            "h_levels": [x[0] for x in h_arr],
            "issues": issues,
        },
    )


def check_positions(status: Dict) -> CheckResult:
    """BLOCK 3: POSITIONS (EXECUTOR layer).
    5W2H What: n_open, day_loss, halted
    5W2H Why:  vị thế mồ côi / loss cap breach = rủi ro tài chính
    5W2H How:  đọc open[], day_loss, halted từ status.json
    5W2H HowMuch: n_open > 4 = FAIL, day_loss < -30 AND NOT halted = FAIL
    """
    open_pos = status.get("open", [])
    day_loss = status.get("day_loss", 0.0) or 0.0
    halted   = status.get("halted", False)
    n_open   = len(open_pos)

    issues: List[str] = []
    st = "PASS"

    if n_open > K_CONTEXT_MAX:
        issues.append(f"K violation: {n_open} open > K={K_CONTEXT_MAX}")
        st = "FAIL"

    if day_loss < DAILY_LOSS_CAP and not halted:
        issues.append(f"day_loss={day_loss:.2f} < cap {DAILY_LOSS_CAP} nhưng halted={halted}")
        st = "FAIL"
    elif day_loss < DAILY_LOSS_CAP and halted:
        issues.append(f"day_loss={day_loss:.2f} = cap (halted=True, đúng)")
        st = "WARN"  # At cap, expected

    observed = f"open={n_open} day_loss={day_loss:+.2f} halted={halted}"
    whys = [
        f"1. Why n_open={n_open}? → MOM1 K=4 cho phép 4 lệnh đồng thời (by design)",
        "2. Why day_loss negative? → TIME/ROL exits đóng lệnh lỗ (PnL negative accumulate)",
        "3. Why not halted? → at_daily_cap property chưa trigger (day_loss chưa đủ -30)",
        "4. Why breach without halt? → note_closed() không gọi (exit RPC fail trước note_closed)",
        "5. ROOT: check exit_log DB — nếu có exit nhưng day_loss không đổi → bug note_closed trong executor",
    ]

    return CheckResult(
        block="3_POSITIONS",
        what=f"open positions, day_loss, halted state",
        observed=observed,
        status=st,
        evidence=f"status.json → open={n_open}, day_loss={day_loss}, halted={halted}",
        whys=whys,
        detail={
            "n_open": n_open, "day_loss": day_loss, "halted": halted,
            "positions": open_pos, "issues": issues,
        },
    )


def check_telemetry(metrics: Dict) -> CheckResult:
    """BLOCK 4: TELEMETRY (DATA layer).
    5W2H What: n_entries/n_exits today, PnL, last update
    5W2H Why:  không telemetry → không audit trail → không trace PnL (Law 3)
    5W2H How:  sqlite3 query entry_log + exit_log
    5W2H HowMuch: n=0 trong ngày = WARN (bot idle?), last > 1h = WARN
    """
    now = int(time.time())
    n_entries = metrics.get("n_entries_today", 0)
    n_exits   = metrics.get("n_exits_today", 0)
    pnl_today = metrics.get("pnl_today", 0.0)
    last_entry = metrics.get("last_entry_ts")
    last_exit  = metrics.get("last_exit_ts")

    latest_ts = max(last_entry or 0, last_exit or 0, 0)
    age = (now - latest_ts) if latest_ts else None

    issues: List[str] = []
    st = "PASS"

    if n_entries == 0 and n_exits == 0:
        issues.append("Không có entry/exit nào hôm nay — bot idle hoặc không fire lệnh")
        st = "WARN"
    elif age is not None and age > NO_TELEMETRY_S:
        issues.append(f"Telemetry cuối {age//60}m trước — bot không có lệnh gần đây")
        st = "WARN"

    observed = (
        f"today: entries={n_entries} exits={n_exits} pnl={pnl_today:+.2f}$ "
        f"last_update={'N/A' if age is None else f'{age//60}m trước'}"
    )

    whys = [
        "1. Why no entries? → strategy gate (window, K, halted) chặn entry",
        "2. Why gate blocking? → ngoài WINDOWS / K full / halted=True",
        "3. Why K full? → 4 vị thế mở không close (TP không fire, TIME chưa tới)",
        "4. Why TP không fire? → TP modify fail (RPC broken) hoặc TP đặt sai giá",
        "5. ROOT: check exit_log — nếu exit có nhưng PnL=0 → executor.exit() không đọc được profit",
    ]

    return CheckResult(
        block="4_TELEMETRY",
        what=f"entry_log/exit_log rows today, PnL, last update",
        observed=observed,
        status=st,
        evidence=f"sqlite3 data/scalp5.db → entry_log+exit_log (ts > {metrics.get('day_start', 0)})",
        whys=whys,
        detail={
            "n_entries": n_entries, "n_exits": n_exits,
            "pnl_today": pnl_today, "age_s": age,
            "issues": issues,
        },
    )


def check_supervisor() -> CheckResult:
    """BLOCK 5: SUPERVISOR (WATCHDOG layer).
    5W2H What: PID alive, STREAM STALLED count, backoff state
    5W2H Why:  supervisor không hoạt động → WS stall tiếp = bot chết hẳn
    5W2H How:  os.kill(pid,0) + grep "STREAM STALLED" logs/scalp5.log
    5W2H HowMuch: PID dead = FAIL, stalled ≥ 3 = FAIL
    """
    # PID check
    pid_alive = False
    pid_str   = ""
    if PID_FILE.exists():
        pid_str = PID_FILE.read_text().strip()
        pid_alive = is_pid_alive(pid_str)

    # StreamStalled count (last 200 log lines to cover full session)
    log_tail = read_log_tail(n_lines=200)
    stalled_n = log_tail.count("STREAM STALLED")
    backoff_refs = [f"backoff={b}s" for b in (30, 60, 120, 300) if f"backoff={b}s" in log_tail]

    issues: List[str] = []
    st = "PASS"

    if not pid_alive:
        issues.append(f"PID {pid_str or 'unknown'} dead — bot process không còn chạy")
        st = "FAIL"
    if stalled_n >= STALL_FAIL_N:
        issues.append(f"STREAM STALLED ×{stalled_n} (≥{STALL_FAIL_N}) — supervisor weak, cần can thiệp")
        st = "FAIL"
    elif stalled_n > 0:
        issues.append(f"STREAM STALLED ×{stalled_n} (backoff {backoff_refs[-1] if backoff_refs else '?'} active)")
        st = "WARN"

    observed = f"pid={'ALIVE' if pid_alive else 'DEAD'} ({pid_str}) stalled={stalled_n} backoff={backoff_refs[-1] if backoff_refs else 'N/A'}"

    whys = [
        f"1. Why PID dead? → main.py crash / OOM / SIGTERM không captured",
        "2. Why crash? → unhandled exception trong run() (không wrap trong main() supervisor)",
        "3. Why StreamStalled? → tick stale > 300s (WebSocket chết im lặng)",
        "4. Why WebSocket dead? → MetaAPI cloud gateway stuck-sync (connectedToBroker=True, sync=None)",
        "5. ROOT: stuck-sync escalation (redeploy terminal) chỉ chạy 1 lần/chu kỳ; "
        "nếu vẫn fail sau 3× backoff → cần redeploy thủ công qua MetaAPI console",
    ]

    return CheckResult(
        block="5_SUPERVISOR",
        what="PID liveness, StreamStalled count, backoff state",
        observed=observed,
        status=st,
        evidence=f"logs/scalp5.pid={pid_str} · grep 'STREAM STALLED' logs/scalp5.log (tail 200)",
        whys=whys,
        detail={
            "pid": pid_str, "pid_alive": pid_alive,
            "stalled_n": stalled_n, "backoff_refs": backoff_refs,
            "issues": issues,
        },
    )


def check_entry_quality() -> CheckResult:
    """BLOCK 6: ENTRY QUALITY (from DB).

    5W2H What:  win rate, exit distribution (TP/TIME), drift alignment, loss streak
    5W2H Why:   chất lượng entry → PnL; TP rate cao = timing tốt, TIME rate cao = entry sai
    5W2H How:   JOIN entry_log + exit_log hôm nay (exit_log = bot-initiated exits only)
    5W2H HowMuch: win_rate < 40% = WARN · streak_loss ≥ 3 = FAIL · TP rate < 25% = WARN

    Karpathy Law 0: atomic = 1 lệnh = entry_px → exit_px → PnL. Không hindsight.
    Karpathy Law 3: bằng chứng = số liệu cụ thể từ DB, không phải "có vẻ ổn".
    Karpathy Law 9: baseline = 11 entries/4 exits hôm nay → win_rate, TP rate là baseline.

    LƯU Ý: exit_log CHƯA có TP-broker fills (chỉ note_closed → day_loss).
    n_tp_broker_est = ước tính, không empirical (đánh dấu rõ trong output).
    """
    m = load_entry_quality_metrics()
    if not m:
        return CheckResult(
            block="6_ENTRY_QUALITY",
            what="Entry quality (win rate, TP rate, drift alignment)",
            observed="DB unavailable — cannot evaluate",
            status="WARN",
            evidence=f"data/scalp5.db không tồn tại hoặc không đọc được",
        )

    total_entries   = m["total_entries"]
    total_closed_db = m["total_closed_db"]
    win_rate        = m["win_rate"]
    tp_rate         = m["tp_rate"]
    time_rate       = m["time_rate"]
    streak_loss     = m["streak_loss"]
    against_pct     = m["against_frac"]  # fraction 0.0–1.0 → ":{:.0%}" gives %
    total_pnl_db    = m["total_pnl_db"]
    reason_dist     = m["reason_dist"]

    issues: List[str] = []
    st = "PASS"

    # Check 1: Win rate (trên bot-initiated exits)
    if total_closed_db > 2 and win_rate < WIN_RATE_WARN:
        issues.append(f"win_rate={win_rate:.0%} < {WIN_RATE_WARN:.0%} (trên {total_closed_db} exits)")
        st = "WARN"

    # Check 2: Loss streak (≥3 = FAIL — strategy đang "bị đánh")
    if streak_loss >= STREAK_LOSS_FAIL:
        issues.append(f"streak_loss={streak_loss} (≥{STREAK_LOSS_FAIL}) — strategy đang gặp khó")
        st = "FAIL"

    # Check 3: TP rate (low = nhiều TIME/ROL exits = entry sai timing)
    if total_closed_db > 2 and tp_rate < TP_RATE_FAIL:
        issues.append(f"TP rate={tp_rate:.0%} < {TP_RATE_FAIL:.0%} — nhiều lệnh TIME/ROL (entry sai timing)")
        if st == "PASS":
            st = "WARN"

    # Check 4: Against-drift entry ratio (cao hơn = entry quality tốt hơn)
    if total_entries >= 3 and against_pct < 20:
        issues.append(f"against-drift={against_pct:.0%} — đa số lệnh vào WITH momentum (đuổi giá)")

    observed = (
        f"entries={total_entries} · closed_db={total_closed_db} "
        f"(+{m['n_tp_broker_est']} TP-broker est) · "
        f"win_rate={win_rate:.0%} · TP={tp_rate:.0%} TIME={time_rate:.0%} · "
        f"against-drift={against_pct:.0%} · streak_loss={streak_loss} · "
        f"pnl_db={total_pnl_db:+.2f}$"
    )

    whys = [
        "1. Why win_rate low? → Nhiều lệnh TIME exit (PnL < 0 sau 10m) — entry không đúng timing",
        "2. Why TIME exits? → MOM1 TIME_STOP=10m nhưng giá không chạy ≥ 1.5pts trong 10m",
        "3. Why giá không chạy? → Entry WITH momentum (đuổi đỉnh/đáy) — giá đã chạy rồi, vào muộn",
        "4. Why WITH momentum? → MOM_PUB_PTS pullback không đủ (0.8pts chưa chạm) → arm không fire",
        "5. ROOT: check against-drift% — nếu < 30% → tăng MOM_PUB_PTS hoặc dùng FZ_FADE để flip entry",
    ]

    return CheckResult(
        block="6_ENTRY_QUALITY",
        what="Win rate, TP/TIME distribution, drift alignment, loss streak",
        observed=observed,
        status=st,
        evidence=f"sqlite3 data/scalp5.db → entry_log+exit_log (ts > day_start)",
        whys=whys,
        detail={
            "total_entries": total_entries,
            "total_closed_db": total_closed_db,
            "n_tp_broker_est": m["n_tp_broker_est"],
            "win_rate": win_rate,
            "wins": m["wins"], "losses": m["losses"],
            "total_pnl_db": round(total_pnl_db, 2),
            "avg_pnl_closed": round(m["avg_pnl_closed"], 2),
            "tp_rate": tp_rate, "time_rate": time_rate,
            "against_frac":    against_pct,
            "streak_loss": streak_loss,
            "reason_dist": reason_dist,
            "issues": issues,
        },
    )


def check_structure_resistance(status: Dict) -> CheckResult:
    """BLOCK 7: STRUCTURE AT STRONG LEVELS (from status.json).

    5W2H What:  strong zones (touches≥2), price proximity, box range, structure density
    5W2H Why:   tại điểm cản mạnh → biến động cao, FZ_FADE nên active; box hẹp → MOM1 yếu
    5W2H How:   L[]/H[] từ status.json; strong = confirmed AND touches ≥ FZ_MIN_TOUCH
    5W2H HowMuch: in_zone=True = WARN (high variance) · box < 2.0 = WARN (range-bound)

    Karpathy Law 0: 'cản mạnh' = 2+ nến M1 test cùng vùng giá (fractal ±2 → S-level).
                    Không cần dữ liệu tương lai — touches đếm từ quá khứ.
    Karpathy Law 5: I/O = đọc status.json (1 file, ~500B). CPU = so sánh px vs levels.
    Karpathy Law 10: 'cản mạnh giống như chốt cửa: càng nhiều người thử mở (touches),
                      càng khó phá qua (break probability thấp, bounce probability cao)'.
    """
    px      = status.get("px", 0)
    L_arr   = status.get("L", [])   # [[px, touches, confirmed], ...]
    H_arr   = status.get("H", [])

    if not px:
        return CheckResult(
            block="7_STRUCTURE_RESISTANCE",
            what="Strong level structure, price proximity, box range",
            observed="px=0 (bot chưa có tick) — không thể đánh giá cấu trúc",
            status="WARN",
            evidence="status.json px=0",
        )

    # Strong levels: confirmed AND touches ≥ FZ_MIN_TOUCH
    strong_l = sorted(lv[0] for lv in L_arr if lv[2] and lv[1] >= FZ_MIN_TOUCH)
    strong_h = sorted(lv[0] for lv in H_arr if lv[2] and lv[1] >= FZ_MIN_TOUCH)

    # Nearest resistance/support (strong levels only)
    nearest_res = min([h for h in strong_h if h > px], default=None)
    nearest_sup = max([l for l in strong_l if l < px], default=None)

    # Nearest ANY confirmed level (stronger signal)
    conf_h_above = sorted(lv[0] for lv in H_arr if lv[2] and lv[0] > px)
    conf_l_below = sorted((lv[0] for lv in L_arr if lv[2] and lv[0] < px), reverse=True)
    nearest_h_any = conf_h_above[0] if conf_h_above else None
    nearest_l_any = conf_l_below[0] if conf_l_below else None

    # In-zone check (± FZ_BAND_PTS from a strong level)
    in_res_zone = any(abs(px - h) <= FZ_BAND_PTS for h in strong_h)
    in_sup_zone = any(abs(px - l) <= FZ_BAND_PTS for l in strong_l)
    in_zone     = in_res_zone or in_sup_zone

    # Box range (strong L min → strong H max)
    box_size = (max(strong_h) - min(strong_l)) if (strong_l and strong_h) else None

    # Structure density: max confirmed levels in any $5 window
    all_conf = sorted([lv[0] for lv in L_arr if lv[2]] + [lv[0] for lv in H_arr if lv[2]])
    max_density = 0
    for i, lv in enumerate(all_conf):
        count = sum(1 for o in all_conf[i:] if o < lv + 5.0)
        max_density = max(max_density, count)

    # Assessment
    issues: List[str] = []
    st = "PASS"

    if in_zone:
        zone_side = "H" if in_res_zone else "L"
        issues.append(
            f"px={px:.1f} tại strong-{zone_side} zone (±{FZ_BAND_PTS}pts) — "
            f"FZ_FADE active, avoid momentum entries, expect bounce"
        )
        st = "WARN"

    if box_size is not None and box_size < TIGHT_BOX_PTS:
        issues.append(
            f"Tight box: {min(strong_l):.1f}→{max(strong_h):.1f} = {box_size:.1f}pts "
            f"(< {TIGHT_BOX_PTS}pts) — range-bound, MOM1 hiệu quả thấp"
        )
        if st == "PASS":
            st = "WARN"

    if not strong_l and not strong_h:
        issues.append(
            "Không có strong level (touches≥2) — S-ladder rebuild mới "
            "(bot vừa start hoặc trend mới phá hết)"
        )
        # Không WARN: fresh structure là bình thường

    observed = (
        f"px={px:.2f} · strong_L={len(strong_l)} strong_H={len(strong_h)} · "
        f"nearest_res={nearest_res if nearest_res else 'N/A'} "
        f"nearest_sup={nearest_sup if nearest_sup else 'N/A'} · "
        f"box={f'{box_size:.1f}pts' if box_size else 'N/A'} "
        f"density_5pts={max_density} · in_zone={in_zone}"
    )

    whys = [
        "1. Why in strong zone? → Price hồi về mức H/L đã test ≥ 2 lần (FZ absorption)",
        "2. Why FZ important? → Level test nhiều = market maker defend, bounce probability cao",
        "3. Why tight box? → Range-bound, net3 < 1.5pts thường xuyên → MOM1 underperform",
        "4. Why no strong levels? → Trend mạnh phá hết S-ladder cũ, ladder đang rebuild",
        "5. ROOT: FZ_FADE + in strong zone → flip entry (LONG→SHORT tại H, SHORT→LONG tại L)",
    ]

    return CheckResult(
        block="7_STRUCTURE_RESISTANCE",
        what="Strong H/L zones, price proximity, box range, structure density",
        observed=observed,
        status=st,
        evidence=(
            f"status.json → px={px}, L={L_arr}, H={H_arr} "
            f"(strong = confirmed + touches≥{FZ_MIN_TOUCH}, band={FZ_BAND_PTS}pts)"
        ),
        whys=whys,
        detail={
            "px": px,
            "strong_l": strong_l,
            "strong_h": strong_h,
            "nearest_resistance": nearest_res,
            "nearest_support":    nearest_sup,
            "nearest_h_any":      nearest_h_any,
            "nearest_l_any":      nearest_l_any,
            "box_size_pts":       box_size,
            "in_res_zone":        in_res_zone,
            "in_sup_zone":        in_sup_zone,
            "max_density_5pts":   max_density,
            "n_conf_levels":     len(all_conf),
            "issues":            issues,
        },
    )


# ─────────────────────────── CYCLE ───────────────────────────

def verify_cycle() -> Dict:
    """1 chu kỳ verify (5 blocks). Return report dict."""
    status  = load_status()
    metrics = load_db_metrics()

    checks = [
        check_tick_stream(status),
        check_strategy_state(status),
        check_positions(status),
        check_telemetry(metrics),
        check_supervisor(),
        check_entry_quality(),
        check_structure_resistance(status),
    ]

    n_fail = sum(1 for c in checks if c.status == "FAIL")
    n_warn = sum(1 for c in checks if c.status == "WARN")
    overall = "FAIL" if n_fail > 0 else "WARN" if n_warn > 0 else "PASS"

    report = {
        "ts": int(time.time()),
        "overall": overall,
        "n_fail": n_fail,
        "n_warn": n_warn,
        "checks": [c.to_dict() for c in checks],
    }

    # Write report JSON
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Human-readable summary (stdout + verify log)
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"\n{'='*62}",
        f"  SCALP5 VERIFY · {ts_str} · OVERALL: {overall} (F={n_fail} W={n_warn})",
        f"{'='*62}",
    ]
    for c in checks:
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[c.status]
        lines.append(f"  {icon} [{c.block}] {c.observed}")
        if c.status != "PASS":
            lines.append(f"     {''.join(f'  {w}' for w in c.whys[:2])}")
    lines.append(f"  Report: {REPORT.name}")
    lines.append(f"{'='*62}\n")
    summary = "\n".join(lines)
    print(summary)

    # Also write to verify log file (for nohup capture)
    try:
        with open(VERIFY_LOG, "a") as f:
            f.write(summary + "\n")
    except Exception:
        pass

    return report


def exit_code_for(report: Dict) -> int:
    """Map overall status → exit code (0=PASS, 1=WARN, 2=FAIL)."""
    return {"PASS": 0, "WARN": 1, "FAIL": 2}[report["overall"]]


# ─────────────────────────── MAIN ───────────────────────────

CYCLE_SECONDS = 300  # 5 minutes

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="XAU_SCALP5 5-min verification loop")
    parser.add_argument("--once", action="store_true", help="Run once, exit (for cron)")
    parser.add_argument("--loop", action="store_true", help="Run continuously every 5 min")
    args = parser.parse_args()

    if args.loop:
        print(f"[VERIFY5] Starting 5-min loop (Ctrl+C to stop) → {REPORT}")
        # Handle SIGTERM gracefully
        stop = False
        def _sig_handler(sig, frame):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT,  _sig_handler)

        while not stop:
            report = verify_cycle()
            # Sleep 5 min (interruptible)
            for _ in range(CYCLE_SECONDS):
                if stop:
                    break
                time.sleep(1)
        print("[VERIFY5] Stopped.")
        sys.exit(exit_code_for(report))
    else:
        # Default: run once
        report = verify_cycle()
        sys.exit(exit_code_for(report))


if __name__ == "__main__":
    main()
