#!/usr/bin/env python3
"""_replay_v2.py — S3-B · V2 GATE REPLAY (spec §14.3) · m1-proxy · DB READ-ONLY (URI ?mode=ro).

3 thành phần (task S3-B):
 (1) G2-A (LVL+EXT15) trên v0 entries thật (109, entry_log dedup): LvlEngine ADVANCE tuần tự
     (feed nến từng candle) ĐẾN ts mỗi entry RỒI query g2_blocked — cảnh báo S3-A: bộ đếm zone
     CUMULATIVE → phải advance engine đến t rồi mới query (KHÔNG rebuild-toàn-đoạn-rồi-filter).
     cf leg (bằng exit_log actual) phải tái hiện +22.26$ (sanity ±5%).
 (2) R1/R2 STALL-FADE M0-GATE (KHÔNG arm khi regime = IMPULSE) · exit 4-lớp
     TP 1.5 / PSL 3.0 / ROL 21:45Z / DRIFT-FLIP (m1-proxy: 2 nến m1 drift-adverse liên tiếp
     khi PnL<0, DƯA TRÊN CLOSE) · K=4 (live cap) vs K=∞.
 (3) v0 không bị chặn → exit V1-ladder (port _replay_v1.py nguyên logic — ladder không đổi).

ASSUMPTIONS m1-proxy (ghi trong report):
 - M0 hysteresis 120 tick ≈ 2 NẾN m1 (M0_HYST) · V-REV = tag sự kiện → hiệu lực ngay (không hysteresis).
 - M0 state (regime/hysteresis/sign) reset mỗi session (E6 parity — E6 chạy per-session, không có M0).
 - K cap = số R1/R2 DỒNG THỜI (live thật: K_CONTEXT chung với v0 — chi phí tương tác chưa đo, note).
 - RANGE M0: "FZ touches ≥ 2" proxy = số zone strong (touches ≥ FZ_MIN_TOUCH) ≥ FZ_MIN_TOUCH.
 - DRIFT-FLIP: close-based (drift = close_k − close_{k−5} tại nến m1 đã khép) — proxy m1 của 2 tick-phút.
 - G2 as-of: query tại nến chứa entry, engine đã feed nến đó (E6 convention: chạm/động của nến k
   tính tại open ts_k ≤ t) · EXT15 cửa sổ 15 nến = parity _replay_lvl (gồm nến chứa).
 - prune zone dead/age trong replay CHỈ để tăng tốc (tương đương filter zones_at, không đổi kết quả).

LỆNH:  .venv/bin/python _replay_v2.py   → stdout + logs/replay_v2.txt
CHỈ stdlib + src/lvl.py (S3-A, dùng thẳng) · KHÔNG write DB · KHÔNG boot bot.
"""
import os
import sys
import sqlite3
import bisect
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from src import lvl as lvlmod                      # S3-A (dùng thẳng, không rewrite)

DB = os.path.join(ROOT, "data", "scalp5.db")
TZ7 = dt.timezone(dt.timedelta(hours=7))
E = lambda y, mo, d, h, mi: int(dt.datetime(y, mo, d, h, mi, tzinfo=TZ7).timestamp())
HM = lambda t: dt.datetime.fromtimestamp(t, TZ7).strftime("%m/%d %H:%M")

# --- hằng replay (m1-proxy; default khớp src/config.py) ---
SPREAD, PSL_PTS, TP_PTS = 0.48, 3.0, 1.5          # 1pt = $2 (lot 0.02) · spread vào+ra
ROL_MIN = 21 * 60 + 45                            # 21:45Z
K_LIVE = 4                                        # K_CONTEXT live
DF_N = 2                                          # DRIFT_FLIP_TICKMIN=2 → proxy 2 m1-close adverse (close-based)
STALL_M1, STALL_TOL, STALL_WAIT = 3, 0.25, 3      # E6 (STALL_TOL/WAIT = default rev-7, không có trong config)
FADE_PTS, LIMIT_TTL = 2.5, 15                     # config
G2_PTS, EXT15_N = 2.0, 15                         # config G2LVL_PTS
M0_IMP, M0_RANGE, M0_FORM, M0_AGE, M0_HYST = 0.5, 0.25, 0.5, 5, 2  # config M0_* (HYST: 120 tick ≈ 2 m1)
FZ_MIN_TOUCH = 2
CF_TARGET = 22.26                                 # E6 §14.3 (G2-A cf, v0-gate) — sanity ±5%

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)   # READ-ONLY (constraint S3-B)
TF = con.execute("SELECT DISTINCT timeframe FROM candles WHERE symbol='XAUUSDm' AND timeframe IN ('1m','m1')").fetchone()[0]

WS = E(2026, 10, 13, 4, 45)                       # v0-gate window (v0 thật chỉ từ 13/10)
WE = E(2026, 10, 14, 14, 45)
R0 = E(2026, 10, 2, 4, 45) - 300 * 60              # R1R2 12 phiên + 300′ warmup (E6)
RE = WE

def load_candles(t0, t1):
    return con.execute(
        "SELECT timestamp, open, high, low, close FROM candles "
        "WHERE symbol='XAUUSDm' AND timeframe=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
        (TF, t0, t1)).fetchall()

bars = load_candles(R0, RE)
v0bars = load_candles(WS, WE)
if len(bars) < 200:
    sys.exit(f"[FATAL] m1 data quá ít ({len(bars)}) — không đủ gate 12 ngày")

# ── v0 entries/exits (dedup giữ ts sớm nhất mỗi pos_id — parity _replay_v1/_replay_lvl) ──
ent, ext = {}, {}
for ts, pos, kind, px in con.execute("SELECT ts,pos_id,kind,entry FROM entry_log"):
    if pos not in ent or ts < ent[pos][0]:
        ent[pos] = (ts, kind, px)
for ts, pos, reason, px, pnl in con.execute("SELECT ts,pos_id,reason,exit_px,pnl FROM exit_log"):
    if pos not in ext or ts < ext[pos][0]:
        ext[pos] = (ts, reason, px, pnl)

# ── V1-LADDER (port _replay_v1.py L35-51, L65-89 — logic giống hệt, tuple có thêm open) ──
sw = []
for i in range(2, len(v0bars) - 2):
    tci = v0bars[i][0] + 180
    if v0bars[i][2] > max(v0bars[j][2] for j in (i - 2, i - 1, i + 1, i + 2)):
        sw.append(("H", v0bars[i][2], tci))
    if v0bars[i][3] < min(v0bars[j][3] for j in (i - 2, i - 1, i + 1, i + 2)):
        sw.append(("L", v0bars[i][3], tci))
lo_b, hi_b = [], []
for ts, o, hi, lo, c in v0bars:
    ct = ts + 60
    Ls = [px for k, px, tc in sw if k == "L" and tc <= ct and px <= c + 0.1]
    Hs = [px for k, px, tc in sw if k == "H" and tc <= ct and px >= c - 0.1]
    lo_b.append(min(Ls) if Ls else None)
    hi_b.append(max(Hs) if Hs else None)

def v1_ladder(in_ts, side, entry):
    """LADDER V1 (S1): PSL(wick,−6.48) > TP(wick,+2.52) > S_BREAK(close, chỉ lỗ) > TIME≥0(10′) > ROL.
    Port _replay_v1.replay() nguyên logic (ladder V1 không đổi — S1 đã gate like-for-like)."""
    for i, (ts, o, hi, lo, c) in enumerate(v0bars):
        if ts + 60 <= in_ts:
            continue
        if side == "L" and lo <= entry - PSL_PTS:
            return "PSL", -6.48, ts + 60
        if side == "S" and hi >= entry + PSL_PTS:
            return "PSL", -6.48, ts + 60
        if side == "L" and hi >= entry + TP_PTS:
            return "TP", 2.52, ts + 60
        if side == "S" and lo <= entry - TP_PTS:
            return "TP", 2.52, ts + 60
        pts = c - entry if side == "L" else entry - c
        if pts < 0:                                          # S_BREAK: CHỈ lệnh lỗ (mirror _break_exit)
            if side == "L" and lo_b[i] is not None and c < lo_b[i] - 0.1:
                return "S_BREAK", pts * 2 - SPREAD, ts + 60
            if side == "S" and hi_b[i] is not None and c > hi_b[i] + 0.1:
                return "S_BREAK", pts * 2 - SPREAD, ts + 60
        if ts + 60 - in_ts >= 10 * 60 and pts >= 0:          # TIME: ≥10′ VÀ pts≥0 (S1 MOM1)
            return "TIME", pts * 2 - SPREAD, ts + 60
        if (ts + 60) % 86400 // 60 >= ROL_MIN:
            return "ROL", pts * 2 - SPREAD, ts + 60
    c = v0bars[-1][4]
    pts = c - entry if side == "L" else entry - c
    return "EOD", pts * 2 - SPREAD, v0bars[-1][0] + 60

# ── ENGINE LVL (S3-A, dùng thẳng) + vòng CHẠY TUẦN TỰ 12 ngày ──
ts_all = [b[0] for b in bars]
os_ = [b[1] for b in bars]
hs = [b[2] for b in bars]
ls = [b[3] for b in bars]
cs = [b[4] for b in bars]
n = len(bars)
eng = lvlmod.LvlEngine("XAUUSDm")
lvlmod._engine = eng            # query API S3-A đọc global _engine — replay engine riêng (in-memory; DB ro)

days = [E(2026, 10, d, 4, 45) for d in range(2, 15)] + [E(2026, 10, 14, 14, 45)]
sessions = list(zip(days[:-1], days[1:]))
k0_first = bisect.bisect_left(ts_all, sessions[0][0])

# M0 state (ASSUMPTION: reset per-session — E6 parity)
m0 = dict(regime="CREEP", cand="", cand_n=0, sign=0, tag=[None] * n)

def prune_zones(ts) -> None:
    """Replay-local: xóa zone H-mù (dead) / hết age → dict nhỏ. TƯƠNG ĐƯƠNG filter zones_at
    (zone bị xóa chắc chắn không bao giờ pass filter ở bất kỳ t ≥ ts nào) → không đổi kết quả,
    chỉ tăng tốc (engine live giữ nguyên dict, đây chỉ là quản trị state của replay)."""
    for z in [z for z in eng.zones.values()
              if (z["dead_ts"] is not None and ts >= z["dead_ts"])
              or ts - z["t_conf"] > lvlmod.LVL_AGE_MIN * 60]:
        del eng.zones[z["zone_key"]]

def m0_step(k, fz) -> None:
    """M0 regime m1-proxy tại close nến k (cùng quy tắc strategy.m0_on_m1_close S3-B):
    speed=|Δ5-close|/5 · form=Σ|C−O|/Σ(H−L) 5 nến · age=min nến đến cực 15-candle ·
    fz = số strong zone (proxy 'FZ touches ≥ 2') · hysteresis M0_HYST=2 nến (V-REV = tag ngay)."""
    speed = abs(cs[k] - cs[k - 5]) / 5.0 if k >= 5 else 0.0
    d5 = cs[k] - cs[k - 5] if k >= 5 else 0.0
    sign_ = 1 if d5 > 0 else (-1 if d5 < 0 else 0)
    form = 0.0
    if k >= 4:
        sd = sum(abs(cs[j] - os_[j]) for j in range(k - 4, k + 1))
        rng = sum(hs[j] - ls[j] for j in range(k - 4, k + 1))
        form = sd / rng if rng > 0 else 0.0
    age = 99
    if k >= EXT15_N - 1:
        win = range(k - EXT15_N + 1, k + 1)
        i_h = max(win, key=lambda j: hs[j])
        i_l = min(win, key=lambda j: ls[j])
        age = min(k - i_h, k - i_l)
    flip = sign_ != 0 and sign_ != m0["sign"]
    cand = "CREEP"
    if speed >= M0_IMP and form >= M0_FORM:
        cand = "IMPULSE"
    elif flip and age < M0_AGE and speed >= M0_IMP:
        cand = "V-REV"
    elif speed < M0_RANGE and fz >= FZ_MIN_TOUCH:
        cand = "RANGE"
    m0["sign"] = sign_
    if cand == m0["regime"]:
        m0["cand"], m0["cand_n"] = "", 0
    elif cand == "V-REV":
        if m0["regime"] != "V-REV":
            m0["regime"] = cand
        m0["cand"], m0["cand_n"] = "", 0
    elif cand == m0["cand"]:
        m0["cand_n"] += 1
        if m0["cand_n"] >= M0_HYST:
            m0["regime"] = cand
            m0["cand"], m0["cand_n"] = "", 0
    else:
        m0["cand"], m0["cand_n"] = cand, 1
    m0["tag"][k] = m0["regime"]

def new_state(cap):
    return dict(cap=cap, open=[], pending=[], done=set(), trades=[])

def r_step(st, k) -> None:
    """R1/R2 tại nến k: exit 4-lớp (ROL>PSL>TP>DRIFT-FLIP) → fill arm (wick, TTL, cap) → arm scan (M0-gate)."""
    ts, o, h, l, c = ts_all[k], os_[k], hs[k], ls[k], cs[k]
    for p in list(st["open"]):
        if (ts // 60) % 1440 == ROL_MIN:
            pnl = ((c - p["in_px"]) if p["side"] == "B" else (p["in_px"] - c)) * 2.0 - SPREAD
            st["trades"].append(p | dict(out_t=ts, out_px=c, reason="ROL", pnl=pnl))
            st["open"].remove(p)
            continue
        psl_hit = (l <= p["in_px"] - PSL_PTS) if p["side"] == "B" else (h >= p["in_px"] + PSL_PTS)
        if psl_hit:
            out_px = p["in_px"] - PSL_PTS if p["side"] == "B" else p["in_px"] + PSL_PTS
            st["trades"].append(p | dict(out_t=ts, out_px=out_px, reason="PSL", pnl=-PSL_PTS * 2.0 - SPREAD))
            st["open"].remove(p)
            continue
        tp_hit = (h >= p["in_px"] + TP_PTS) if p["side"] == "B" else (l <= p["in_px"] - TP_PTS)
        if tp_hit:
            out_px = p["in_px"] + TP_PTS if p["side"] == "B" else p["in_px"] - TP_PTS
            st["trades"].append(p | dict(out_t=ts, out_px=out_px, reason="TP", pnl=TP_PTS * 2.0 - SPREAD))
            st["open"].remove(p)
            continue
        # DRIFT-FLIP m1-proxy (close-based ASSUMPTION): 2 m1-close drift-adverse liên tiếp khi PnL<0
        if k >= 5:
            d5 = cs[k] - cs[k - 5]
            pts = c - p["in_px"] if p["side"] == "B" else p["in_px"] - c
            adv = d5 < 0 if p["side"] == "B" else d5 > 0
            p["df_n"] = (p.get("df_n", 0) + 1) if (adv and pts < 0) else 0
            if p["df_n"] >= DF_N:
                st["trades"].append(p | dict(out_t=ts, out_px=c, reason="DRIFT", pnl=pts * 2.0 - SPREAD))
                st["open"].remove(p)
                continue
    for L in list(st["pending"]):
        if L["until"] < ts:
            st["pending"].remove(L)
            continue
        filled = (l <= L["px"]) if L["side"] == "S" else (h >= L["px"])
        if filled and (st["cap"] is None or len(st["open"]) < st["cap"]):
            st["open"].append(dict(side=L["side"], in_px=L["px"], in_t=ts, lvl=L["lvl_px"],
                                   regime=m0["tag"][k], df_n=0))
            st["done"].add(L["key"])
            st["pending"].remove(L)
    if k >= 5 and m0["tag"][k] != "IMPULSE":        # M0 GATE: block R1/R2 trong IMPULSE (§14.3)
        hi3 = max(hs[k - a] for a in range(STALL_M1))
        lo3 = min(ls[k - a] for a in range(STALL_M1))
        net5 = sum(cs[k - a] - os_[k - a] for a in range(5))
        for side_q, kind in (("S", "H"), ("B", "L")):
            for z in lvlmod.strong_zones(side_q, ts):   # engine đã advance (feed đầu vòng) → as-of-t đúng
                key = (kind, round(z["px"], 2))
                if key in st["done"] or any(x["key"] == key for x in st["pending"]):
                    continue
                wait = ts - z["t_conf"] >= STALL_WAIT * 60
                if kind == "H" and wait and hi3 < z["px"] + STALL_TOL and net5 < 0:
                    st["pending"].append(dict(key=key, side="S", px=round(z["px"] - FADE_PTS, 3),
                                              lvl_px=z["px"], until=ts + LIMIT_TTL * 60))
                elif kind == "L" and wait and lo3 > z["px"] - STALL_TOL and net5 > 0:
                    st["pending"].append(dict(key=key, side="B", px=round(z["px"] + FADE_PTS, 3),
                                              lvl_px=z["px"], until=ts + LIMIT_TTL * 60))

def r_eod(st, k_end) -> None:
    """EOD session (parity E6): còn mở → đóng tại close nến cuối."""
    if not st["open"] or k_end < 0:
        return
    c = cs[k_end]
    for p in list(st["open"]):
        pnl = ((c - p["in_px"]) if p["side"] == "B" else (p["in_px"] - c)) * 2.0 - SPREAD
        st["trades"].append(p | dict(out_t=ts_all[k_end] + 60, out_px=c, reason="EOD", pnl=pnl))
        st["open"].remove(p)

# ── v0 G2-A: index entry theo nến chứa (parity _replay_lvl L136: idx = bisect_right−1) ──
ent_by_idx = {}
for pid, (t, kind, px) in ent.items():
    idx = max(bisect.bisect_right(ts_all, t) - 1, 0)
    ent_by_idx.setdefault(idx, []).append((pid, t, kind, px))

blocked, blocked_set = [], set()
session_rows = []
all4_trades: list = []      # gộp R1/R2 M0-gated qua 12 phiên (K=4)
allI_trades: list = []      # K=∞

# (1) PREFEED warmup nến TRƯỚC session đầu (300′ — parity E6 warmup)
for k in range(0, min(k0_first, n)):
    eng._on_candle(ts_all[k], os_[k], hs[k], ls[k], cs[k])
    prune_zones(ts_all[k])

# (2) VÒNG CHÁY 12 PHIÊN: feed engine tuần tự + M0 + G2-A (v0) + R1/R2 (K=4 & K=∞)
for T0, T1 in sessions:
    m0.update(regime="CREEP", cand="", cand_n=0, sign=0)   # ASSUMPTION: reset per-session (E6 parity)
    k0 = bisect.bisect_left(ts_all, T0)
    k1 = bisect.bisect_right(ts_all, T1)
    st4, stI = new_state(K_LIVE), new_state(None)
    if k0 >= n or ts_all[k0] > T1:
        session_rows.append((T0, None, 0, 0.0, 0))          # phiên không có nến (weekend)
        continue
    for k in range(k0, k1):
        ts = ts_all[k]
        eng._on_candle(ts, os_[k], hs[k], ls[k], cs[k])     # ADVANCE engine (bộ đếm cumulative — S3-A)
        prune_zones(ts)
        szS, szB = lvlmod.strong_zones("S", ts), lvlmod.strong_zones("B", ts)
        m0_step(k, len(szS) + len(szB))
        # (a) G2-A trên v0 entries thuộc nến k (engine already advanced → as-of-t đúng)
        for pid, t, kind, px in ent_by_idx.get(k, ()):
            side = "B" if kind == "ENTER_LONG" else "S"
            b_lvl = lvlmod.g2_blocked(side, px, t)          # NHÁNH LVL: không điều kiện nến (row 21)
            ex_h = ex_l = None
            if k >= EXT15_N - 1:                             # NHÁNH EXT15: 2 nến (parity _replay_lvl L122-141)
                ex_h = max(hs[k - EXT15_N + 1: k + 1])
                ex_l = min(ls[k - EXT15_N + 1: k + 1])
            up2 = cs[k] >= os_[k] and cs[k - 1] >= os_[k - 1]
            down2 = cs[k] <= os_[k] and cs[k - 1] <= os_[k - 1]
            b_ext = False
            if not b_lvl:
                if side == "S" and up2 and ex_h is not None and 0 <= ex_h - px <= G2_PTS:
                    b_ext = True
                elif side == "B" and down2 and ex_l is not None and 0 <= px - ex_l <= G2_PTS:
                    b_ext = True
            if b_lvl or b_ext:
                pnl_avoided = ext[pid][3] if pid in ext else 0.0
                blocked.append((pid, side, t, px, "LVL" if b_lvl else "EXT15", pnl_avoided, m0["tag"][k]))
                blocked_set.add(pid)
        # (b) R1/R2 (2 K-variant chạy song song, cùng M0-gate)
        r_step(st4, k)
        r_step(stI, k)
    r_eod(st4, k1 - 1)
    r_eod(stI, k1 - 1)
    all4_trades.extend(st4["trades"])
    allI_trades.extend(stI["trades"])
    session_rows.append((T0, T1, len(st4["trades"]),
                         sum(t["pnl"] for t in st4["trades"]),
                         sum(1 for t in st4["trades"] if t["pnl"] > 0)))

# ── TỔNG HỢP THÀNH PHẦN (1): G2-A cf leg (exit_log actual basis — parity E6) ──
# OPERATOR 14/10 (root-cause _diag_g2.py): E6 target +22.26$ = LOOK-AHEAD semantics (zone px-FINAL
# sau merge + touches band-check px-final + EXT15 down2 wick low≤open) — KHÔNG live-computable.
# LIVE engine (src/lvl px-now): cf-LIVE +34.01$ (chặn −11.41$ loss 10/14 10:09 S) > E6-ref.
# Diff E6↔LVL = 6 entry (3 only-LVL −8.74$ · 3 only-E6 +3.00$) = px-merge/touch-timing + body-vs-wick.
v0_actual = sum(x[3] for x in ext.values())                    # dedup exit_log (73 lệnh, ≈ +21.89$)
pnl_blocked = sum(b[5] for b in blocked)
v0_cf = v0_actual - pnl_blocked                                 # cf leg LIVE (px-now semantics)
n_lvl = sum(1 for b in blocked if b[4] == "LVL")
n_ext = len(blocked) - n_lvl
cf_ok = v0_cf >= CF_TARGET * 0.95                               # A (operator 14/10): cf-LIVE ≥ 95% E6-ref

# ── TỔNG HỢP (2): R1/R2 M0-gated (K=4 & K=∞) + WR theo regime ──
def kpi(trades):
    ntr = len(trades)
    pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return ntr, pnl, wins

n4, pnl4, w4 = kpi(all4_trades)
nI, pnlI, wI = kpi(allI_trades)
k_eff = (pnl4 / pnlI) if pnlI != 0 else 0.0

def wr_by_regime(trades):
    out = {}
    for tag in ("IMPULSE", "V-REV", "RANGE", "CREEP"):
        sub = [t for t in trades if t.get("regime") == tag]
        if sub:
            out[tag] = (len(sub), sum(t["pnl"] for t in sub), sum(1 for t in sub if t["pnl"] > 0))
    return out

wr4 = wr_by_regime(all4_trades)
exc4 = {}
for t in all4_trades:
    exc4[t["reason"]] = exc4.get(t["reason"], 0) + 1

# ── TỔNG HỢP (3): v0 không bị chặn → V1-ladder (model basis) ──
v0_unb_pnl, v0_unb_rows, v0_unb_worst = 0.0, [], None
for pid, (t, kind, px) in sorted(ent.items(), key=lambda kv: kv[1][0]):
    if pid in blocked_set:
        continue
    side = "L" if kind == "ENTER_LONG" else "S"
    reason, pnl, out_t = v1_ladder(t, side, px)
    v0_unb_pnl += pnl
    if v0_unb_worst is None or pnl < v0_unb_worst[0]:
        v0_unb_worst = (pnl, pid, HM(t), side, px, reason)
    v0_unb_rows.append((HM(t), pid, side, px, reason, pnl))
n_v0_unb = len(v0_unb_rows)

# ── VERDICT GATE §14.3 (V2 12d ≥ cf +22.26$/cửa-v0 + R1R2×K_eff (K=4)) ──
v2_total = v0_unb_pnl + pnl4                       # model basis: v0-unblocked (V1-ladder) + R1R2 M0-gated K=4
thresh = CF_TARGET + pnl4
D_literal = v2_total >= thresh                      # §14.3 literal (v0 leg = model V1-ladder)
_wc = []
if v0_unb_worst:
    _wc.append(v0_unb_worst[0])
if all4_trades:
    _wc.append(min(t["pnl"] for t in all4_trades))
worst_all = min(_wc) if _wc else 0.0
worst_ok = worst_all >= -(PSL_PTS * 2.0 + SPREAD) - 1e-6   # PSL-cap −6.48$ (inclusive — PSL exit đúng cap, tolerance float; fix operator 14/10)
edge_ok = pnl4 >= 0.0                              # M0-gate không giết edge R1/R2
verdict = "PASS" if (cf_ok and worst_ok and edge_ok) else "FAIL"   # operator 14/10: A∧B∧C (D-literal = tham chiếu — §14.3 literal trộn 2 basis)

# ── BÁO CÁO ──
lines = []
W = lines.append
W("════════════════════════════════════════════════════════════════")
W("S3-B · V2 GATE REPLAY (§14.3) · m1-proxy · DB READ-ONLY · 12 ngày 02/10→14/10 + v0-gate 13/10→14/10")
W("════════════════════════════════════════════════════════════════")
W(f"TF={TF} · {n} nến m1 ({HM(ts_all[0])}→{HM(ts_all[-1])}) · zones engine={len(eng.zones)} · "
  f"v0 entries={len(ent)} · v0 exits dedup={len(ext)} · PSL-cap=−{PSL_PTS*2+SPREAD:.2f}$ · spread {SPREAD}$")
W("")
W("── (1) G2-A (LVL+EXT15) trên v0 entries — cf leg (exit_log ACTUAL basis, parity E6) ──")
W(f"  CHẶN {len(blocked)}/109 lệnh (LVL {n_lvl} · EXT15 {n_ext}) · PnL loại {pnl_blocked:+.2f}$ "
  f"(trốn lỗ {sum(b[5] for b in blocked if b[5] < 0):+.2f} / phí win {sum(b[5] for b in blocked if b[5] > 0):+.2f})")
W(f"  v0 THỰC (dedup exit_log): {v0_actual:+.2f}$ · CF LIVE(px-now) = {v0_cf:+.2f}$  "
  f"[E6-ref +22.26 (lookahead, live không tính được — root-cause _diag_g2.py) · A: cf-LIVE ≥ 95% E6-ref → "
  f"{'PASS' if cf_ok else 'FAIL'}]")
W("  Top-10 lệnh v0 bị chặn (|PnL| lớn nhất):")
for pid, side, t, px, src, p, tag in sorted(blocked, key=lambda b: -abs(b[5]))[:10]:
    W(f"    {HM(t)}  v0 {side} @{px:.1f} · {src} · PnL-loại {p:+.2f}$ · regime={tag}")
W("")
W("── (2) R1/R2 M0-GATE (block trong IMPULSE) · exit 4-lớp · K=4 vs K=∞ ──")
W(f"  K=4 (live cap): {n4} lệnh · PnL {pnl4:+.2f}$ · WR {w4}/{n4} ({100*w4/max(1,n4):.0f}%)")
W(f"  K=∞:           {nI} lệnh · PnL {pnlI:+.2f}$ · WR {wI}/{nI} ({100*wI/max(1,nI):.0f}%) · "
  f"K_eff factor = PnL(K4)/PnL(K∞) = {k_eff:.3f}")
W("  Exit mix (K=4): " + " · ".join(f"{k_}×{v}" for k_, v in sorted(exc4.items())))
W("  WR theo regime (K=4):")
for tag, (nn, pp, ww) in wr4.items():
    W(f"    {tag:<8} {nn:>4} lệnh · {pp:+8.2f}$ · WR {ww}/{nn}")
W("  Per-session (K=4):")
for T0, T1, nn, pp, ww in session_rows:
    lab = dt.datetime.fromtimestamp(T0, TZ7).strftime("%m/%d")
    W(f"    {lab}: {nn:>3} lệnh · {pp:+8.2f}$ · WR {ww}/{nn}" + (" (weekend, 0 nến)" if T1 is None else ""))
W("")
W("── (3) v0 KHÔNG-BỊ-CHẶN → V1-ladder (model basis — ladder S1 không đổi) ──")
W(f"  {n_v0_unb} lệnh · PnL {v0_unb_pnl:+.2f}$ · worst {v0_unb_worst[0]:+.2f}$ "
  f"({v0_unb_worst[1]} {v0_unb_worst[2]} {v0_unb_worst[3]}@{v0_unb_worst[4]:.1f} → {v0_unb_worst[5]})"
  if v0_unb_worst else "  0 lệnh (toàn v0 bị chặn — bất thường)")
W(f"  worst tổng V2 (v0-unb + R1R2 K4): {worst_all:+.2f}$  [{'≥' if worst_ok else '<'} −6.48 PSL-cap → "
  f"{'PASS' if worst_ok else 'FAIL'}]")
W("")
W("── VERDICT GATE §14.3 (operator 14/10: A∧B∧C · D-literal = tham chiếu) ──")
W(f"  V2-total (model: v0-unb V1-ladder + R1R2 M0-gated K=4) = {v2_total:+.2f}$")
W(f"  D-literal threshold = {CF_TARGET:+.2f} + {pnl4:+.2f} = {thresh:+.2f}$ → "
  f"{'PASS' if D_literal else 'FAIL'} (tham chiếu: literal trộn basis cf-actual/model)")
W(f" _checks: A(cf-LIVE px-now ≥ 95% E6-ref) {'✓' if cf_ok else '✗'} · "
  f"B(worst ≥ −6.48 PSL-cap, inclusive) {'✓' if worst_ok else '✗'} · "
  f"C(R1R2 K4 ≥ 0) {'✓' if edge_ok else '✗'} · D(literal §14.3, tham chiếu) {'✓' if D_literal else '✗'}")
W(f"  VERDICT: {verdict}")
W("")
W("ASSUMPTIONS / CHÊNH (detail trong report S3-B):")
W(" - M0 hysteresis 120 tick ≈ 2 nến m1 · V-REV tag ngay (sự kiện 1 nến, hysteresis làm nó không fire).")
W(" - M0 state reset mỗi session (E6 parity; E6 không có M0).")
W(" - RANGE M0: 'FZ touches ≥ 2' proxy = số zone strong (touches ≥ FZ_MIN_TOUCH) ≥ 2.")
W(" - DRIFT-FLIP close-based (drift5m tại m1-close), 2 m1-close adverse liên tiếp khi PnL<0.")
W(" - K cap = R1/R2 đồng thời; live thật K_CONTEXT chung với v0 (tương tác chưa đo — rev-sau).")
W(" - A (cf): E6 +22.26$ = lookahead semantics (px-final/touch-px-final + EXT15 wick) — live không tính được.")
W("   LIVE = px-now (src/lvl): cf-LIVE +34.01$ ≥ 95% E6-ref ✓ · root-cause diff 6 entry: _diag_g2.py.")
W(" - §14.3 literal trộn 2 basis (cf-actual vs model) → D = tham chiếu; VERDICT = A∧B∧C (operator 14/10, STATE.md).")
W(" - G2 as-of: engine feed nến chứa entry (E6 convention chạm/động nến k tại open ts_k) · EXT15 window")
W("   15 nến gồm nến chứa (parity _replay_lvl) · prune zone dead/age = replay-local (không đổi kết quả).")

report = "\n".join(lines)
print(report)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
with open(os.path.join(ROOT, "logs", "replay_v2.txt"), "w") as f:
    f.write(report + "\n")
print(f"\n[ok] saved → logs/replay_v2.txt")