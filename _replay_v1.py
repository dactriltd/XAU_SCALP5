#!/usr/bin/env python3
"""S1 14/10 — REPLAY LADDER V1 trên các lệnh v0 THẬT (offline, CHỈ stdlib, đọc DB).

Ladder V1 (ưu tiên TRONG MỖI nến 1m): PSL(−3.0) > TP(+1.5) > S_BREAK > TIME(10′, pts≥0) > ROL(21:45Z)
- PSL/TP dùng WICK nến (cùng nến trúng cả hai → PSL thắng) · S_BREAK/TIME/ROL dùng CLOSE
- S_BREAK mirror _break_exit: swings M1 (nến i: high>high 4 nến kề = H · low<low 4 nến kề = L),
  t_conf = ts nến i+2 (+60s) · L chưa-broken = L ≤ c+0.1 · H chưa-broken = H ≥ c−0.1 ·
  BUY: c < lo−0.1 → thoát tại c · SELL: c > hi+0.1 → thoát tại c (CHỈ lệnh lỗ, mirror pnl_pts<0)
- 1pt = $2 (lot 0.02) · spread vào+ra = 0.48$/lệnh · PSL fixed −6.48$ · TP fixed +2.52$
- Window: 13/10 04:45+07 → 14/10 14:45+07 · hết data → EOD tại close cuối
"""
import os, sqlite3, datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "data", "scalp5.db")      # DB 20MB thật (sculp5.db 0-byte = rác, không đụng)
TZ7 = dt.timezone(dt.timedelta(hours=7))
SPREAD, PSL_PTS, TP_PTS = 0.48, 3.0, 1.5
TSTOP_S, ROL_MIN = 10 * 60, 21 * 60 + 45          # TIME 10′ · ROL 21:45 UTC
USD = lambda pts: pts * 2 - SPREAD                # pts → $ (1pt=$2, trừ spread)
HM = lambda t: dt.datetime.fromtimestamp(t, TZ7).strftime("%m/%d %H:%M")

con = sqlite3.connect(DB)

# ── 1) NẾN 1m trong window (SELECT DISTINCT timeframe trước: '1m' hay 'm1') ──
TF = con.execute(
    "SELECT DISTINCT timeframe FROM candles WHERE symbol='XAUUSDm' AND timeframe IN ('1m','m1')"
).fetchone()[0]
WS = int(dt.datetime(2026, 10, 13, 4, 45, tzinfo=TZ7).timestamp())
WE = int(dt.datetime(2026, 10, 14, 14, 45, tzinfo=TZ7).timestamp())
bars = [r for r in con.execute(
    "SELECT timestamp, high, low, close FROM candles "
    "WHERE symbol='XAUUSDm' AND timeframe=? AND timestamp>=? AND timestamp<? ORDER BY timestamp",
    (TF, WS, WE))]

# ── 2) SWINGS M1 ±2 nến; t_conf = ts nến i+2 (+60s = đúng lúc nến i+2 khép) ──
sw = []
for i in range(2, len(bars) - 2):
    tci = bars[i][0] + 180
    if bars[i][1] > max(bars[j][1] for j in (i - 2, i - 1, i + 1, i + 2)):
        sw.append(("H", bars[i][1], tci))
    if bars[i][2] < min(bars[j][2] for j in (i - 2, i - 1, i + 1, i + 2)):
        sw.append(("L", bars[i][2], tci))
# tiền-tính lo/hi theo CLOSE c của MỖI nến (độc lập với lệnh):
# L chưa-broken (t_conf ≤ close_t và L ≤ c+0.1) → lo = min · H chưa-broken (H ≥ c−0.1) → hi = max
lo_b, hi_b = [], []
for ts, hi, lo, c in bars:
    ct = ts + 60
    Ls = [px for k, px, tc in sw if k == "L" and tc <= ct and px <= c + 0.1]
    Hs = [px for k, px, tc in sw if k == "H" and tc <= ct and px >= c - 0.1]
    lo_b.append(min(Ls) if Ls else None)
    hi_b.append(max(Hs) if Hs else None)

# ── 3) LỆNH v0 THẬT: DEDUP giữ ts sớm nhất mỗi pos_id ──
ent, ext = {}, {}
for r in con.execute("SELECT ts, pos_id, kind, entry FROM entry_log"):
    e = ent.get(r[1])
    if e is None or r[0] < e[0]:
        ent[r[1]] = (r[0], r[2], r[3])
for r in con.execute("SELECT ts, pos_id, reason, exit_px, pnl FROM exit_log"):
    e = ext.get(r[1])
    if e is None or r[0] < e[0]:
        ext[r[1]] = (r[0], r[2], r[3], r[4])

# ── 4) REPLAY MỖI LỆNH: từ ts entry, đi tuần tự nến 1m (close đầu tiên = nến chứa entry) ──
def replay(in_ts, side, entry):
    for i, (ts, hi, lo, c) in enumerate(bars):
        if ts + 60 <= in_ts:
            continue                          # nến khép trước entry → chưa có giá nào
        if side == "L" and lo <= entry - PSL_PTS:        # PSL (wick, ưu tiên đầu)
            return "PSL", -6.48, ts + 60
        if side == "S" and hi >= entry + PSL_PTS:
            return "PSL", -6.48, ts + 60
        if side == "L" and hi >= entry + TP_PTS:          # TP (wick)
            return "TP", 2.52, ts + 60
        if side == "S" and lo <= entry - TP_PTS:
            return "TP", 2.52, ts + 60
        pts = c - entry if side == "L" else entry - c     # pnl tại close (pts)
        if pts < 0:                                        # S_BREAK: CHỈ lệnh lỗ (mirror _break_exit)
            if side == "L" and lo_b[i] is not None and c < lo_b[i] - 0.1:
                return "S_BREAK", USD(pts), ts + 60
            if side == "S" and hi_b[i] is not None and c > hi_b[i] + 0.1:
                return "S_BREAK", USD(pts), ts + 60
        if ts + 60 - in_ts >= TSTOP_S and pts >= 0:        # TIME: tuổi ≥10′ VÀ pts≥0
            return "TIME", USD(pts), ts + 60
        if (ts + 60) % 86400 // 60 >= ROL_MIN:             # ROL: phút-ngày UTC ≥ 21:45
            return "ROL", USD(pts), ts + 60
    c = bars[-1][3]                                        # hết data → EOD tại close cuối
    pts = c - entry if side == "L" else entry - c
    return "EOD", USD(pts), bars[-1][0] + 60


def replay_v0(in_ts, side, entry):
    """LADDER V0 (live MOM1-NOW 13/10–14/10): TP | TIME 10′ VÔ ĐIỀU KIỆN | ROL.
    Dùng CÙNG model nến 1m như replay() → cohort so-sánh like-for-like (kể cả 36 lệnh
    'chưa thoát' không có exit row: v0-thật = 0.0, V0-MODEL = PnL mô hình hoá)."""
    for i, (ts, hi, lo, c) in enumerate(bars):
        if ts + 60 <= in_ts:
            continue
        if side == "L" and hi >= entry + TP_PTS:
            return "TP", 2.52, ts + 60
        if side == "S" and lo <= entry - TP_PTS:
            return "TP", 2.52, ts + 60
        pts = c - entry if side == "L" else entry - c
        if ts + 60 - in_ts >= TSTOP_S:                     # TIME vô điều kiện (v0 live)
            return "TIME", USD(pts), ts + 60
        if (ts + 60) % 86400 // 60 >= ROL_MIN:
            return "ROL", USD(pts), ts + 60
    c = bars[-1][3]
    pts = c - entry if side == "L" else entry - c
    return "EOD", USD(pts), bars[-1][0] + 60

rows = []
for pid, (in_ts, kind, entry) in sorted(ent.items(), key=lambda kv: kv[1][0]):
    side = "L" if kind == "ENTER_LONG" else "S"
    r1, p1, t1 = replay(in_ts, side, entry)
    r0, p0, _t0 = replay_v0(in_ts, side, entry)
    a = ext.get(pid)
    v0r, v0p = (a[1], a[3]) if a else ("—", None)
    rows.append((HM(in_ts), pid, side, entry, v0r, v0p, r1, p1, t1,
                 None if a is None else round(p1 - a[3], 2), r0, p0))

# ── 5) TẢNG trade-by-trade + TỔNG KẾT + GATES G1/G2 ──
print(f"TF={TF} · {len(bars)} nến ({HM(bars[0][0])}→{HM(bars[-1][0])}) · {len(sw)} swings · "
      f"{len(ent)} entry / {len(ext)} exit (dedup giữ ts sớm nhất)")
hdr = f"{'entry+07':>11} {'pos_id':>10} {'sd':>2} {'entry$':>9} | {'v0 ACTUAL':>12} | {'v1 LADDER':>16} | {'delta$':>7}"
print(hdr)
print("-" * 118)
for r in rows:
    v0 = f"{r[4]:>5} {r[5]:+7.2f}" if r[5] is not None else "—(chưa thoát)"
    dl = f"{r[9]:+.2f}" if r[9] is not None else "—"
    print(f"{r[0]:>11} {r[1]:>10} {r[2]:>2} {r[3]:>9.1f} | {v0:>12} | "
          f"{r[6]:>7} {r[7]:+7.2f} {HM(r[8])} | {dl:>7}")

def s(pl):
    return sum(x for x in pl if x is not None)

# COHORT như nhau (cùng 109 entry thật). 2 ladder chạy trên CÙNG replay engine:
#   v1_tot      = PSL+BREAK+TIME≥0  (S1 fix)
#   v0_model_tot = TP|TIME-vô-đk|ROL (ladder v0 live, KHÔNG PSL/BREAK) → counterfactual
v1_tot     = s([x[7] for x in rows])
v1_worst   = min(x[7] for x in rows)
v0_model_tot = s([replay_v0(ts_, "L" if k == "ENTER_LONG" else "S", px)[1]
                  for (ts_, k, px) in ent.values()])
v0_full = s([a[3] for a in ext.values()])          # THỰC: 73 lệnh có exit-row
v0_1410 = s([a[3] for a in ext.values()
             if dt.datetime.fromtimestamp(a[0], TZ7).day == 14])
print("=" * 118)
print(f"[THỰC]  v0 dedup (73 lệnh có exit-row): full {v0_full:+.2f}$ (≈+21.89$) · 14/10 {v0_1410:+.2f}$ (≈+13.25$)")
print(f"[MODEL] v0-ladder (TP|TIME|ROL, KHÔNG PSL): {v0_model_tot:+.2f}$  ← counterfactual 'nếu chưa S1'")
print(f"[MODEL] v1-ladder (PSL+BREAK+TIME≥0):       {v1_tot:+.2f}$ · worst-lệnh {v1_worst:+.2f}$")
g1 = v1_tot >= v0_model_tot
g2 = v1_worst >= -6.48
print(f"G1 (v1_model ≥ v0_model, like-for-like): {'PASS' if g1 else 'FAIL'}  "
      f"(Δ = {v1_tot - v0_model_tot:+.2f}$)")
print(f"G2 (v1_worst ≥ −6.48$ = PSL-cap): {'PASS' if g2 else 'FAIL'}")
top = sorted([x for x in rows if x[9] is not None], key=lambda x: -x[9])[:5]
print("Top-5 delta lớn nhất (V1−v0):")
for r in top:
    print(f"  {r[0]} {r[1]} {r[2]} in {r[3]:.1f} · v0 {r[4]} {r[5]:+.2f} → "
          f"v1 {r[6]} {r[7]:+.2f} · delta {r[9]:+.2f}")
