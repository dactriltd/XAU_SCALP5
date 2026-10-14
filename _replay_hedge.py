#!/usr/bin/env python3
"""_replay_hedge.py — S4-HEDGE 12 NGÀY đối kháng (15/10) · DB READ-ONLY (URI ?mode=ro) · CHỐNG D4.

So sánh 2 CẤU HÌNH trên CÙNG 12 phiên (02/10→14/10) với ScalpStrategy THẬT (4 tick/m1 nến,
parity test_offline/_replay_v2):
  A: Baseline V2 — HEDGE_ENABLE=False (PSL 3.0pts cắt trực tiếp, không có orchestrator)
  B: S4-HEDGE + UNIFIED ORCHESTRATOR — HEDGE_ENABLE=True (LOCK 1.2 · BREAK 1.0 · BASKET_TP 0.50)
GATE 3 (3 tiêu chí PASS):
  1. worst_basket_usd(B) ≥ −6.48 (không rổ nào vượt trần PSL-cũ)
  2. Mọi rổ PRUNE_BREAK (branch=LOCKED) có lỗ ròng ≈ −3.36 (±0.10)
  3. PnL tổng 12d (B) ≥ PnL tổng (A)
ASSUMPTIONS (ghi rõ, parity _replay_v2/test_offline):
  - KHÔNG LVL engine (strong_zones → [] fail-open) → R1/R2 arms vắng mặt, G2 không block (A≡B)
  - M0 state reset mỗi phiên (E6 parity) · m0_on_m1_close gọi mỗi nến m1 khép (parity main hook)
  - PnL$ mỗi vị thế = pts×OZ − SPREAD (OZ=$2/pt · SPREAD=2×0.24$=0.48$ vào+ra) · 1pt=1$@LOT0.02→×2
  - hedge_credit sync như main.exit_action: khi HEDGE_TAKE ok → root["hedge_credit"]=pnl leg thật
  - rổ (basket) = root + mọi leg; PnL rổ = tổng PnL thành phần · EOD (14/10 14:45+07 cut) đóng nốt
CHẠY:  ./.venv/bin/python _replay_hedge.py  → stdout + logs/replay_hedge.txt
KHÔNG write DB · KHÔNG boot bot · KHÔNG đụng runtime thư mục gốc (D4).
"""
import os
import sys
import sqlite3
import datetime as dt
from collections import Counter
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from src import config as C          # noqa: E402
from src.scalp_strategy import ScalpStrategy   # noqa: E402

# ── DB READ-ONLY (D4): worktree → ../XAU_SCALP5/data/scalp5.db · fallback thư mục gốc ──
def open_ro():
    for cand in ("../XAU_SCALP5/data/scalp5.db", "data/scalp5.db"):
        p = os.path.abspath(os.path.join(ROOT, cand))
        if os.path.exists(p):
            return sqlite3.connect(f"file:{p}?mode=ro", uri=True), cand
    sys.exit("[FATAL] không tìm thấy scalp5.db (worktree lẫn root) — không chạy read-only")

con, DB_SRC = open_ro()
TF = con.execute(
    "SELECT DISTINCT timeframe FROM candles WHERE symbol='XAUUSDm' AND timeframe IN ('1m','m1')"
).fetchone()[0]

TZ7 = dt.timezone(dt.timedelta(hours=7))
E = lambda y, mo, d, h, mi: int(dt.datetime(y, mo, d, h, mi, tzinfo=TZ7).timestamp())
HM = lambda t: dt.datetime.fromtimestamp(t, TZ7).strftime("%m/%d %H:%M")

OZ = C.LOT * 100.0                   # $/pt (0.02 lot = 2oz = $2/pt)
SPREAD = 2 * C.SPREAD_PTS            # $0.48 round-trip (vào + ra)
PSL_CAP = -(C.PSL_PTS * OZ + SPREAD)  # −6.48$ (trần PSL-cũ + spread)
LOCKED_TARGET, TOL = -3.36, 0.10     # D3: lỗ ròng đóng băng khóa @ −1.2pts

# 12 phiên 02/10→14/10 (04:45+07 = 21:45Z) + cut cuối 14/10 14:45+07 (parity _replay_v2)
days = [E(2026, 10, d, 4, 45) for d in range(2, 15)] + [E(2026, 10, 14, 14, 45)]
sessions = list(zip(days[:-1], days[1:]))
W0 = days[0] - 300 * 60             # warmup 300′ trước phiên đầu (parity E6)
WE = days[-1]

wins = ((0, C.ROLLOVER_MIN),) if C.WINDOWS_ALL else C.WINDOWS


def load_candles(t0, t1):
    return con.execute(
        "SELECT timestamp, open, high, low, close FROM candles "
        "WHERE symbol='XAUUSDm' AND timeframe=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
        (TF, t0, t1)).fetchall()


warmup = load_candles(W0, W0 + 300 * 60)
if len(warmup) < 10:
    sys.exit(f"[FATAL] warmup m1 quá ít ({len(warmup)}) — DB thiếu dữ liệu trước 02/10")
sess_bars = [(T0, T1, load_candles(T0, T1 - 60)) for T0, T1 in sessions]
n_total = sum(len(b) for _, _, b in sess_bars)
if n_total < 5000:
    sys.exit(f"[FATAL] m1 12 ngày quá ít ({n_total} nến) — không đủ gate")


def ns(**over) -> SimpleNamespace:
    b = SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if k.isupper()})
    for k, v in over.items():
        setattr(b, k, v)
    return b


def run_variant(hedges_on: bool):
    """Chạy 1 cấu hình trên 12 phiên → (report-dict). Strategy LIÊN TỤC (live-like),
    M0 reset mỗi phiên (E6 parity). Rổ = {root_id: {pnl, kind, branch, closed}}."""
    cfg = ns(HEDGE_ENABLE=hedges_on)
    s = ScalpStrategy(cfg)
    # warmup (parity main seed: feed nến, KHÔNG decide)
    for ts, o, h, l, c in warmup:
        for dt_, px in ((10, o), (25, h), (40, l), (58, c)):
            s.on_tick(ts + dt_, px)
    open_pos, next_id = [], 1
    exit_mix = Counter()
    per_session = []        # (T0, n_bars, pnl_session)
    baskets = {}            # root_id → {"pnl", "kind", "branch", "legs"} (in-place, gộp pnl root+legs)
    pnl_total = 0.0
    n_entries = 0
    for T0, T1, bars in sess_bars:
        # M0 reset per-session (E6 parity — STATE.md _replay_v2 assumption)
        s.m0_regime, s.m0_cand, s.m0_cand_n, s.m0_drift_sign = "CREEP", "", 0, 0
        sess_pnl = 0.0
        if not bars:
            per_session.append((T0, 0, 0.0))
            continue
        for bar in bars:
            ts, o, h, l, c = bar
            for dt_, px in ((10, o), (25, h), (40, l), (58, c)):
                t = ts + dt_
                s.on_tick(t, px)
                acts = s.decide(open_pos, wins, C.ROLLOVER_MIN)
                for a in acts:
                    if a["kind"].startswith("ENTER"):
                        posd = {
                            "id": str(next_id),
                            "side": "L" if a["kind"] == "ENTER_LONG" else "S",
                            "entry": a["px"], "entry_ts": t, "anchor": a.get("anchor"),
                        }
                        if a.get("leg_type") == "HEDGE":
                            posd.update({"parent_id": a.get("parent_id"), "leg_type": "HEDGE",
                                         "hedge_credit": 0.0, "unwound": False,
                                         "wall_px": a.get("anchor")})
                            baskets.setdefault(a["parent_id"],
                                               {"pnl": 0.0, "kind": None, "branch": None, "legs": 0})
                            baskets[a["parent_id"]]["legs"] += 1
                        open_pos.append(posd)
                        next_id += 1
                        n_entries += 1
                    elif a["kind"] == "EXIT":
                        p = next((x for x in open_pos if x["id"] == a["pos_id"]), None)
                        if p is None:
                            continue
                        sgn = 1 if p["side"] == "L" else -1
                        pnl = sgn * (a["px"] - p["entry"]) * OZ - SPREAD
                        open_pos.remove(p)
                        exit_mix[a["reason"]] += 1
                        pnl_total += pnl
                        sess_pnl += pnl
                        if a["reason"] == "HEDGE_TAKE" and p.get("parent_id"):
                            # parity main.exit_action: sync hedge_credit THẬT (pnl leg) vào root
                            root = next((x for x in open_pos if x["id"] == str(p["parent_id"])), None)
                            if root is not None:
                                root["hedge_credit"] = pnl
                            b = baskets.get(p["parent_id"])
                            if b is not None:
                                b["pnl"] += pnl
                        else:
                            # leg → gộp pnl vào rổ theo ROOT (parent_id) · root → rổ của chính nó
                            b = baskets.get(p.get("parent_id") or p["id"])
                            if b is not None:
                                b["pnl"] += pnl
                                # đánh DẤU đóng in-place (KHÔNG snapshot dict(b) tại lúc root đóng —
                                # snapshot sẽ thiếu pnl leg đóng sau cùng tick); thu cuối run
                                if not p.get("parent_id"):
                                    b["kind"] = a["reason"]
                                    b["branch"] = a.get("branch")
                                    b["ts"] = t
                                    b["px"] = a["px"]
            s.m0_on_m1_close(ts + 60, o, h, l, c)      # parity main._m1_close_hook (mỗi m1 khép)
        # EOD fallback (session cut 14/10 14:45+07 / thiếu data — ROL thường đã đóng trước)
        if open_pos:
            cpx = bars[-1][4]
            for p in list(open_pos):
                sgn = 1 if p["side"] == "L" else -1
                pnl = sgn * (cpx - p["entry"]) * OZ - SPREAD
                open_pos.remove(p)
                exit_mix["EOD"] += 1
                pnl_total += pnl
                sess_pnl += pnl
                b = baskets.get(p.get("parent_id") or p["id"])
                if b is not None:
                    b["pnl"] += pnl
                    if not p.get("parent_id"):
                        b["kind"] = b["kind"] or "EOD"
                        b["ts"], b["px"] = ts, cpx
        per_session.append((T0, len(bars), sess_pnl))
    # rổ ĐÓNG = mọi basket đã có exit-kind (pnl = TỒNG root + legs — in-place, đã gộp trọn tick)
    closed_baskets = [dict(b, root_id=k) for k, b in baskets.items() if b.get("kind")]
    return dict(label=("B: S4-HEDGE+ORCH" if hedges_on else "A: Baseline V2"),
                pnl_total=pnl_total, exit_mix=exit_mix, n_entries=n_entries,
                closed_baskets=closed_baskets, per_session=per_session)


resA = run_variant(False)
resB = run_variant(True)

cbA, cbB = resA["closed_baskets"], resB["closed_baskets"]
pb_locked = [b for b in cbB if b["kind"] == "PRUNE_BREAK" and b.get("branch") == "LOCKED"]
pb_unwound = [b for b in cbB if b["kind"] == "PRUNE_BREAK" and b.get("branch") == "UNWOUND"]
pb_span = [b for b in cbB if b["kind"] == "PRUNE_SPAN"]
take_to_tp = [b for b in cbB if b["kind"] == "BASKET_TP"]
worst_basket = min((b["pnl"] for b in cbB), default=0.0)
g1 = worst_basket >= PSL_CAP - 1e-6
g2 = (all(abs(b["pnl"] - LOCKED_TARGET) <= TOL for b in pb_locked)) and len(pb_locked) >= 1
g3 = resB["pnl_total"] >= resA["pnl_total"]

lines = []
W = lines.append
W("════════════════════════════════════════════════════════════")
W("S4-HEDGE REPLAY 12 NGÀY (02/10→14/10) · m1-proxy · DB READ-ONLY")
W("════════════════════════════════════════════════════════════")
W(f"DB={DB_SRC} (mode=ro) · TF={TF} · {n_total} nến · OZ=${OZ:.0f}/pt · SPREAD=${SPREAD:.2f} · "
  f"PSL-cap=−${abs(PSL_CAP):.2f} · wins={'ALLDAY' if C.WINDOWS_ALL else 'SESSION'} · {len(warmup)} nến warmup")
W("")
for r in (resA, resB):
    W(f"── {r['label']} ──")
    W(f"  {r['n_entries']} entries (12d) · PnL tổng {r['pnl_total']:+.2f}$ · "
      f"mix-exit: " + " · ".join(f"{k}×{v}" for k, v in sorted(r["exit_mix"].items())))
    W("  per-session: " + " · ".join(
        f"{dt.datetime.fromtimestamp(T0, TZ7).strftime('%d/%m')} {p:+.1f}$"
        for T0, _, p in r["per_session"]))
    if r is resB:
        W(f"  rổ (basket): {len(cbB)} · HEDGE_TAKE→BASKET_TP {len(take_to_tp)} · "
          f"PRUNE_BREAK LOCKED {len(pb_locked)} · UNWOUND {len(pb_unwound)} · PRUNE_SPAN {len(pb_span)}")
        if pb_locked:
            W(f"  PRUNE_BREAK(LOCKED) lỗ ròng: " + " ".join(f"{b['pnl']:+.2f}$" for b in pb_locked[:12]))
            if len(pb_locked) > 12:
                W(f"    (+{len(pb_locked) - 12} rổ khác)")
        if cbB:
            W(f"  worst_basket {worst_basket:+.2f}$")
    W("")
W("── GATE 3 CHECKS (bắt buộc 3/3) ──")
W(f"  1. worst_basket_usd(B) = {worst_basket:+.2f}$ ≥ {PSL_CAP:.2f}$ → "
  f"{'PASS ✅' if g1 else 'FAIL ❌'}")
W(f"  2. PRUNE_BREAK(LOCKED) {len(pb_locked)} rổ ≈ {LOCKED_TARGET:.2f}$ ±{TOL:.2f}$ "
  f"(outliers: {sum(1 for b in pb_locked if abs(b['pnl'] - LOCKED_TARGET) > TOL)}) → "
  f"{'PASS ✅' if g2 else 'FAIL ❌ (cần ≥1 rổ + mọi rổ trong tolerance)'}")
W(f"  3. PnL 12d: B {resB['pnl_total']:+.2f}$ ≥ A {resA['pnl_total']:+.2f}$ → "
  f"{'PASS ✅' if g3 else 'FAIL ❌'} (diff {resB['pnl_total'] - resA['pnl_total']:+.2f}$)")
verdict = "PASS ✅ (3/3 → FLIP HEDGE_ENABLE=True)" if (g1 and g2 and g3) else "FAIL ❌ (giữ HEDGE_ENABLE=False)"
W(f"  VERDICT GATE 3: {verdict}")
W("")
W("ASSUMPTIONS / CHÊNH:")
W(" - KHÔNG LVL engine (fail-open): R1/R2 arms vắng mặt ở CẢ A lẫn B (fair parity — gate đo S4-HEDGE, không đo R1R2).")
W(" - M0 reset mỗi phiên (E6 parity _replay_v2) · 4 tick/m1 nến (o@10 h@25 l@40 c@58 — parity test_offline).")
W(" - PnL$ = pts×2 − 0.48 (spread round-trip 0.24×2) · vị thế chưa EOD/ROL đóng tại close phiên (fallback).")
W(" - hedge_credit = PnL leg THẬT tại HEDGE_TAKE (parity main.exit_action) · BASKET_TP net = float(root)+credit.")
W(" - PRUNE_LOCKED lý thuyết = (−1.2×2) − 0.96 = −3.36$ (telescoping leg+root tại tick cùng px) — sai số =")
W("   overshoot tick khóa (m1 proxy) → tolerance ±0.10$ theo plan.")

report = "\n".join(lines)
print(report)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
with open(os.path.join(ROOT, "logs", "replay_hedge.txt"), "w") as f:
    f.write(report + "\n")
print(f"\n[ok] saved → logs/replay_hedge.txt ({DB_SRC}, read-only)")
sys.exit(0 if (g1 and g2 and g3) else 2)
