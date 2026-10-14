"""_diag_g2.py — ROOT-CAUSE check A (gate §14.3): cf_lvl = +34.01 (C-B) vs E6 target +22.26.
HYPOTHESIS (SYSTEM-2, AGENTS.md L3): E6 _replay_lvl.py precompute TOÀN TOÁN (zones + touches + dead
được tính sau, band touch check với px-FINAL (max-merge) của zone) = LOOK-AHEAD; src/lvl.py (S3-A)
incremental px-NOW (band check với px tại thời điểm mỗi nến) → lvl ĐẾM THẾ touches early hơn E6
→ nhiều strong-zone hơn → block nhiều hơn (hướng: cf_lvl > cf_e6 ✓ khớp +11.75$).
KỊCH BẢN: (1) replicate E6 (per-session, 300′ warmup, lookahead — faithful port) → cf_e6 ≈ +22.26?
(2) replicate C-B path (engine liên tục R0, prune, G2-A như _replay_v2 L296-314) → cf_lvl ≈ +34.01?
(3) DIFF set block: mọi entry chênh phải có giải thích px-chain/touch-timing (in zone state 2 phía).
DB read-only · stdlib only · lệnh: .venv/bin/python _diag_g2.py
"""
import os
import sys
import sqlite3
import bisect
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from src import lvl as lvlmod  # noqa: E402

DB = os.path.join(ROOT, "data", "scalp5.db")
TZ7 = dt.timezone(dt.timedelta(hours=7))
E = lambda y, mo, d, h, mi: int(dt.datetime(y, mo, d, h, mi, tzinfo=TZ7).timestamp())
HM = lambda t: dt.datetime.fromtimestamp(t, TZ7).strftime("%m/%d %H:%M")

# --- hằng E6 (port _replay_lvl.py L23-43, giá trị rev-7) ---
LVL_TOUCH, LVL_BAND, LVL_SEP_MIN = 2, 0.5, 6
ZONE_PTS, ZONE_SPAN_MIN, LVL_AGE_MIN = 0.5, 30, 240
FADE_PTS, G2_PTS, G2_EXTREME_M1, WARMUP_MIN = 2.5, 2.0, 15, 300

WS, WE = E(2026, 10, 13, 4, 45), E(2026, 10, 14, 14, 45)
R0 = E(2026, 10, 2, 4, 45) - 300 * 60          # warmup khởi đầu engine C-B (như _replay_v2)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
ent, ext = {}, {}
for ts, pos, kind, px, _tp in con.execute("SELECT ts,pos_id,kind,entry,tp FROM entry_log"):
    if pos not in ent or ts < ent[pos][0]:
        ent[pos] = (ts, kind, px)
for ts, pos, reason, px, pnl in con.execute("SELECT ts,pos_id,reason,exit_px,pnl FROM exit_log"):
    if pos not in ext or ts < ext[pos][0]:
        ext[pos] = (ts, reason, px, pnl)
v0_actual = sum(x[3] for x in ext.values())


def e6_session_blocks(T0, T1):
    """E6 LOOK-AHEAD (faithful port _replay_lvl.py L63-147, per-session + 300′ warmup)."""
    m1 = con.execute(
        "SELECT timestamp,open,high,low,close FROM candles WHERE symbol='XAUUSDm' AND timeframe='1m' "
        "AND timestamp BETWEEN ? AND ? ORDER BY timestamp", (T0 - WARMUP_MIN * 60, T1)).fetchall()
    ts_list = [r[0] for r in m1]
    if len(m1) < 60:
        return set(), None
    pivots = []
    for i in range(2, len(m1) - 2):
        if m1[i][2] > max(m1[j][2] for j in (i - 2, i - 1, i + 1, i + 2)):
            pivots.append(dict(px=m1[i][2], kind="H", i=i, t_conf=ts_list[i + 2] + 60))
        if m1[i][3] < min(m1[j][3] for j in (i - 2, i - 1, i + 1, i + 2)):
            pivots.append(dict(px=m1[i][3], kind="L", i=i, t_conf=ts_list[i + 2] + 60))
    zones = []
    for pv in sorted(pivots, key=lambda p: (p["kind"], p["i"])):
        placed = False
        for z in zones:
            if (z["kind"] == pv["kind"] and abs(z["px"] - pv["px"]) <= ZONE_PTS
                    and pv["i"] - z["i_last"] <= ZONE_SPAN_MIN):
                z["px"] = max(z["px"], pv["px"]) if pv["kind"] == "H" else min(z["px"], pv["px"])
                z["i_last"] = pv["i"]
                z["t_conf"] = min(z["t_conf"], pv["t_conf"])
                placed = True
                break
        if not placed:
            zones.append(dict(px=pv["px"], kind=pv["kind"], i_last=pv["i"], t_conf=pv["t_conf"],
                              touches=[], dead_ts=None))
    for z in zones:
        k, P = z["kind"], z["px"]                 # px FINAL (max-merge) — LOOK-AHEAD artifact
        last_touch = None
        for j in range(len(m1)):
            ts_j = m1[j][0]
            if ts_j < z["t_conf"]:
                continue
            if k == "H" and m1[j][4] <= P - FADE_PTS and z["dead_ts"] is None:
                z["dead_ts"] = ts_j
            hit = m1[j][2] >= P - LVL_BAND if k == "H" else m1[j][3] <= P + LVL_BAND
            if hit and (last_touch is None or ts_j - last_touch >= LVL_SEP_MIN * 60):
                z["touches"].append(ts_j)
                last_touch = ts_j

    def zones_at(t):
        out = []
        for z in zones:
            tc, dk = z["t_conf"], z["dead_ts"]
            if tc > t or t - tc > LVL_AGE_MIN * 60 or (dk is not None and t >= dk):
                continue
            if bisect.bisect_right(z["touches"], t) >= LVL_TOUCH:
                out.append(dict(px=z["px"], kind=z["kind"], t_conf=tc,
                                n_touch=len(z["touches"]), dead_ts=dk))
        return out

    def extremes_at(t):
        idx = bisect.bisect_right(ts_list, t) - 1
        if idx < G2_EXTREME_M1:
            return None, None
        win = m1[idx - G2_EXTREME_M1 + 1: idx + 1]
        return max(r[2] for r in win), min(r[3] for r in win)

    blocks = set()
    detail = {}
    for pos, (t, kind, px) in ent.items():
        side = "B" if kind == "ENTER_LONG" else "S"
        if not (T0 <= t < T1):
            continue
        idx = bisect.bisect_right(ts_list, t) - 1
        if idx < 2:
            continue
        up2 = m1[idx][4] >= m1[idx][1] and m1[idx - 1][4] >= m1[idx - 1][1]
        down2 = m1[idx][3] <= m1[idx][1] and m1[idx - 1][3] <= m1[idx - 1][1]
        ex_h, ex_l = extremes_at(t)
        hit = None
        for L in zones_at(t):
            if side == "S" and L["kind"] == "H" and 0 <= L["px"] - px <= G2_PTS:
                hit = ("LVL", L["px"])
                break
            if side == "B" and L["kind"] == "L" and 0 <= px - L["px"] <= G2_PTS:
                hit = ("EXT15" if False else "LVL", L["px"])
                break
        if not hit:
            if side == "S" and up2 and ex_h is not None and 0 <= ex_h - px <= G2_PTS:
                hit = ("EXT15", ex_h)
            elif side == "B" and down2 and ex_l is not None and 0 <= px - ex_l <= G2_PTS:
                hit = ("EXT15", ex_l)
        if hit:
            blocks.add(pos)
            detail[pos] = (side, t, px, hit[0], hit[1])
    return blocks, detail


# ── (2) C-B PATH: engine liên tục (src.lvl) + prune + G2-A như _replay_v2 L282-314 ──
def lvl_engine_blocks():
    bars = con.execute(
        "SELECT timestamp,open,high,low,close FROM candles WHERE symbol='XAUUSDm' AND timeframe='1m' "
        "AND timestamp BETWEEN ? AND ? ORDER BY timestamp", (R0, WE)).fetchall()
    ts_all, os_, hs, ls, cs = (list(x) for x in zip(*[(b[0], b[1], b[2], b[3], b[4]) for b in bars]))
    n = len(bars)
    eng = lvlmod.LvlEngine("XAUUSDm")
    lvlmod._engine = eng

    def prune(ts):
        for z in [z for z in eng.zones.values()
                  if (z["dead_ts"] is not None and ts >= z["dead_ts"])
                  or ts - z["t_conf"] > lvlmod.LVL_AGE_MIN * 60]:
            del eng.zones[z["zone_key"]]

    days = [E(2026, 10, d, 4, 45) for d in range(2, 15)] + [E(2026, 10, 14, 14, 45)]
    sessions = list(zip(days[:-1], days[1:]))
    # ent_by_idx: entry ts → index nến CHỨA (parity C-B L268: idx = bisect_right−1)
    ent_by_idx = {}
    for pos, (t, kind, px) in ent.items():
        idx = max(bisect.bisect_right(ts_all, t) - 1, 0)
        ent_by_idx.setdefault(idx, []).append((pos, t, kind, px))

    # PREFEED warmup (parity C-B L276-279)
    k0_first = bisect.bisect_left(ts_all, sessions[0][0])
    for k in range(0, k0_first):
        eng._on_candle(ts_all[k], os_[k], hs[k], ls[k], cs[k])
        prune(ts_all[k])

    blocks = set()
    detail = {}
    for T0, T1 in sessions:
        k0, k1 = bisect.bisect_left(ts_all, T0), bisect.bisect_right(ts_all, T1)
        if k0 >= n:
            continue
        for k in range(k0, k1):
            ts = ts_all[k]
            eng._on_candle(ts, os_[k], hs[k], ls[k], cs[k])
            prune(ts)
            for pos, t, kind, px in ent_by_idx.get(k, ()):
                side = "B" if kind == "ENTER_LONG" else "S"
                b_lvl = lvlmod.g2_blocked(side, px, t)
                ex_h = ex_l = None
                if k >= G2_EXTREME_M1 - 1:
                    ex_h = max(hs[k - G2_EXTREME_M1 + 1: k + 1])
                    ex_l = min(ls[k - G2_EXTREME_M1 + 1: k + 1])
                up2 = cs[k] >= os_[k] and cs[k - 1] >= os_[k - 1]
                down2 = cs[k] <= os_[k] and cs[k - 1] <= os_[k - 1]
                b_ext = False
                if not b_lvl:
                    if side == "S" and up2 and ex_h is not None and 0 <= ex_h - px <= G2_PTS:
                        b_ext = True
                    elif side == "B" and down2 and ex_l is not None and 0 <= px - ex_l <= G2_PTS:
                        b_ext = True
                if b_lvl or b_ext:
                    blocks.add(pos)
                    zs = lvlmod.strong_zones(side, t)
                    in_band = [z for z in zs if (0 <= z["px"] - px <= G2_PTS if side == "S"
                                                  else 0 <= px - z["px"] <= G2_PTS)]
                    detail[pos] = (side, t, px, "LVL" if b_lvl else "EXT15",
                                   in_band[0] if in_band and b_lvl else None)
    return blocks, detail


# ── CHẠY + SO SÁNH ──
e6_blocks, e6_detail = set(), {}
for T0, T1 in ((WS, E(2026, 10, 14, 4, 45)), (E(2026, 10, 14, 4, 45), WE)):
    b, d = e6_session_blocks(T0, T1)
    e6_blocks |= b
    e6_detail.update(d)
lvl_blocks, lvl_detail = lvl_engine_blocks()

def cf(blocks):
    pnl_b = sum(ext[p][3] for p in blocks if p in ext)
    return v0_actual - pnl_b, pnl_b

cf_e6, pb_e6 = cf(e6_blocks)
cf_lvl, pb_lvl = cf(lvl_blocks)
print(f"v0_actual (dedup exit_log) = {v0_actual:+.2f}$")
print(f"E6 lookahead : block {len(e6_blocks):>3}/109 · PnL-loại {pb_e6:+.2f}$ · cf = {cf_e6:+.2f}$  (target E6 +22.26)")
print(f"LVL (C-B px-now): block {len(lvl_blocks):>3}/109 · PnL-loại {pb_lvl:+.2f}$ · cf = {cf_lvl:+.2f}$  (C-B gate +34.01)")
print(f"repro check: |cf_e6 − 22.26| ≤ 1.11? {abs(cf_e6 - 22.26) <= 1.11} · |cf_lvl − 34.01| ≤ 1.11? {abs(cf_lvl - 34.01) <= 1.11}")
print()

only_lvl = sorted(lvl_blocks - e6_blocks, key=lambda p: -abs(ext.get(p, (0, 0, 0, 0.0))[3]))
only_e6 = sorted(e6_blocks - lvl_blocks, key=lambda p: -abs(ext.get(p, (0, 0, 0, 0.0))[3]))
print(f"DIFF only-LVL (lvl block, E6 không) = {len(only_lvl)} entry · PnL {sum(ext.get(p, (0,0,0,0.0))[3] for p in only_lvl):+.2f}$")
for p in only_lvl[:12]:
    s, t, px, src, z = lvl_detail[p]
    zinfo = (f"L:{z['px']:.2f} tc={HM(z['t_conf'])} dead={z['dead_ts'] and HM(z['dead_ts'])} "
             f"touches={z['touches']}" if z else "EXT15")
    print(f"  {HM(t)} {s} @{px} [{src}] {zinfo} · PnL {ext.get(p, (0,0,0,0.0))[3]:+.2f}$")
print(f"DIFF only-E6 (E6 block, lvl không) = {len(only_e6)} entry · PnL {sum(ext.get(p, (0,0,0,0.0))[3] for p in only_e6):+.2f}$")
for p in only_e6[:12]:
    s, t, px, src, hpx = e6_detail[p]
    print(f"  {HM(t)} {s} @{px} [{src} zone/ext {hpx:.2f}] · PnL {ext.get(p, (0,0,0,0.0))[3]:+.2f}$")

# ── CASE 10:09 S (root-cause chính): px-chain + touch-timing 2 phía ──
print()
print("── deep-dive case 10/14 10:09 S @4163.0 ──")
for p in ent:
    if ent[p][0] > E(2026, 10, 14, 10, 9) - 120 and ent[p][0] < E(2026, 10, 14, 10, 10) + 120 \
            and ent[p][1] != "ENTER_LONG" and abs(ent[p][2] - 4163.0) < 0.1:
        t, px = ent[p][0], ent[p][2]
        print(f"  entry {p} · t={HM(t)} · px={px}")
        print(f"  E6:  block={'YES' if p in e6_blocks else 'no'} {e6_detail.get(p)}")
        s, t2, px2, src, z = lvl_detail.get(p, (None, t, px, None, None))
        print(f"  LVL: block={'YES' if p in lvl_blocks else 'no'} {z}")
