#!/usr/bin/env python3
"""_replay_lvl.py — Replay REV 7 (spec §14) trên DB: LVL M1 rolling ±2 + R1/R2 STALL-FADE + G2-LVL.

MẸO (proxy m1, chưa tick): pivot ±2 tại close nến i+2 · zone gộp 0.5pts/30′ ·
touches ≥ 2 = strong · DEAD = close ∓ 2.5 · R1/R2: stall 3 nến + net5, limit ∓ 2.5 (hạn 15′) ·
exit: TP 1.5 / PSL 3.0 / TIME 10′ / ROL 21:45Z / spread 0.48$ · G2: LVL (không nến) + EXT15 (2 nến,
biến thể A) hay LVL-only (biến thể B).

LỆNH:
  python3 _replay_lvl.py              → pilot 1 ngày 10/14 (soi trade-by-trade)
  python3 _replay_lvl.py --days       → E6: 12 phiên 02/10→14/10 (cửa ship, 2 biến thể G2)

GHI CHÚ: chỉ đo phần cộng của REV 7. Cổng rev 6 (M0, G-DIR, PSL, REVERSE) chưa code —
E6 đầy đủ trên strategy V2 hoàn chỉnh là bước kế tiếp (spec §14.2).
"""
import bisect
import sqlite3
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=7))
DB = "data/scalp5.db"

# --- hằng REV 7 (khởi điểm — E6 quyết fine-tune) ---
LVL_TOUCH = 2          # touches ≥ N = STRONG
LVL_BAND = 0.5         # bán kính chạm (FZ_BAND_PTS)
LVL_SEP_MIN = 6        # 2 chạm cách ≥ 6′ (S1_TOUCH_SEP_MIN)
ZONE_PTS = 0.5         # gộp zone: pivot cùng kind cách ≤ 0.5pts
ZONE_SPAN_MIN = 30     # và trong 30′
LVL_AGE_MIN = 240      # zone hết hạn sau 240′ (FZ_RECENT)
STALL_M1 = 3           # STALL = 3 nến m1 không phá
STALL_TOL = 0.25       # "phá" = vượt mức ±0.25
STALL_WAIT_M1 = 3      # stall phải ≥ 3′ sau t_conf
FADE_PTS = 2.5         # R1/R2: entry = mức ∓ 2.5
LIMIT_TTL_MIN = 15     # hạn mức limit-order
NET5 = 5               # net(C−O) 5 nến = regime proxy
G2_PTS = 2.0           # G2: khoảng cách tới zone/extreme
G2_EXTREME_M1 = 15     # extreme 15 m1 (G2 rev 6)
TP_PTS, PSL_PTS = 1.5, 3.0
SPREAD_USD = 0.48      # 0.24pts × $2/pt (vào+ra)
TIME_STOP_M1 = 10
ROL_UTC_MIN = 21 * 60 + 45   # 21:45Z = 04:45+07
K_CAP = 4
WARMUP_MIN = 300       # nến warmup trước phiên (zone + touches)

E = lambda y, mo, d, h, mi: int(datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp())
HMS = lambda ts: datetime.fromtimestamp(ts, TZ).strftime("%H:%M:%S")


def load_v0(db):
    ent = {}
    for ts, pos, kind, px, _tp in db.execute("SELECT ts,pos_id,kind,entry,tp FROM entry_log"):
        if pos not in ent or ts < ent[pos]["ts"]:
            ent[pos] = dict(ts=ts, side="B" if kind == "ENTER_LONG" else "S", px=px)
    ext = {}
    for ts, pos, reason, px, pnl in db.execute("SELECT ts,pos_id,reason,exit_px,pnl FROM exit_log"):
        if pos not in ext or ts < ext[pos]["ts"]:
            ext[pos] = dict(ts=ts, reason=reason, px=px, pnl=pnl)
    return ent, ext


def run_replay(db, T0, T1, ent, ext, g2_variant="A"):
    """Replay 1 đoạn [T0, T1]. Trả (r1r2_trades, blocked, v0_blocked_pnl, n_zones)."""
    m1 = db.execute(
        "SELECT timestamp, open, high, low, close FROM candles "
        "WHERE symbol='XAUUSDm' AND timeframe='1m' AND timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp", (T0 - WARMUP_MIN * 60, T1)).fetchall()
    ts_list = [r[0] for r in m1]
    if len(m1) < 60:  # phiên không có dữ liệu (weekend/holiday)
        return [], [], 0.0, 0
    k0 = bisect.bisect_left(ts_list, T0)

    # pivot ±2 tại close nến i+2
    pivots = []
    for i in range(2, len(m1) - 2):
        h, l = m1[i][2], m1[i][3]
        if h > max(m1[j][2] for j in (i - 2, i - 1, i + 1, i + 2)):
            pivots.append(dict(px=h, kind="H", i=i, t_conf=ts_list[i + 2] + 60))
        if l < min(m1[j][3] for j in (i - 2, i - 1, i + 1, i + 2)):
            pivots.append(dict(px=l, kind="L", i=i, t_conf=ts_list[i + 2] + 60))

    # zone: gộp pivot cùng kind (≤ ZONE_PTS, ≤ ZONE_SPAN_MIN nến)
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

    # touches + dead (precompute)
    for z in zones:
        k, P = z["kind"], z["px"]
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
                out.append(dict(px=z["px"], kind=z["kind"], t_conf=tc))
        return out

    def extremes_at(t):
        idx = bisect.bisect_right(ts_list, t) - 1
        if idx < G2_EXTREME_M1:
            return None, None
        win = m1[idx - G2_EXTREME_M1 + 1: idx + 1]
        return max(r[2] for r in win), min(r[3] for r in win)

    # ===== G2-LVL (nếu đoạn này có v0 entries) =====
    blocked = []
    v0_blocked_pnl = 0.0
    for pos, e in ent.items():
        t, px, side = e["ts"], e["px"], e["side"]
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
                hit = ("LVL", L["px"]); break
            if side == "B" and L["kind"] == "L" and 0 <= px - L["px"] <= G2_PTS:
                hit = ("LVL", L["px"]); break
        if not hit and g2_variant == "A":
            if side == "S" and up2 and ex_h is not None and 0 <= ex_h - px <= G2_PTS:
                hit = ("EXT15", ex_h)
            elif side == "B" and down2 and ex_l is not None and 0 <= px - ex_l <= G2_PTS:
                hit = ("EXT15", ex_l)
        if hit:
            pnl_avoided = ext[pos]["pnl"] if pos in ext else 0.0
            blocked.append((pos, side, t, px, hit[1], hit[0], pnl_avoided))
            if pos in ext:
                v0_blocked_pnl += pnl_avoided

    # ===== R1/R2 =====
    pending, open_pos, done = [], [], set()
    r1r2 = []
    for k in range(k0, len(m1)):
        ts, o, h, l, c = m1[k]
        rol_hit = (ts // 60) % 1440 == ROL_UTC_MIN
        for p in list(open_pos):
            age = (ts - p["in_t"]) // 60
            if rol_hit:
                pnl = ((c - p["in_px"]) if p["side"] == "B" else (p["in_px"] - c)) * 2.0 - SPREAD_USD
                r1r2.append(p | dict(out_t=ts, out_px=c, reason="ROL", pnl=pnl))
                open_pos.remove(p); continue
            psl_hit = (l <= p["in_px"] - PSL_PTS) if p["side"] == "B" else (h >= p["in_px"] + PSL_PTS)
            tp_hit = (h >= p["in_px"] + TP_PTS) if p["side"] == "B" else (l <= p["in_px"] - TP_PTS)
            if psl_hit:
                out_px = p["in_px"] - PSL_PTS if p["side"] == "B" else p["in_px"] + PSL_PTS
                r1r2.append(p | dict(out_t=ts, out_px=out_px, reason="PSL", pnl=-PSL_PTS * 2.0 - SPREAD_USD))
                open_pos.remove(p); continue
            if tp_hit:
                out_px = p["in_px"] + TP_PTS if p["side"] == "B" else p["in_px"] - TP_PTS
                r1r2.append(p | dict(out_t=ts, out_px=out_px, reason="TP", pnl=TP_PTS * 2.0 - SPREAD_USD))
                open_pos.remove(p); continue
            if age >= TIME_STOP_M1:
                pnl = ((c - p["in_px"]) if p["side"] == "B" else (p["in_px"] - c)) * 2.0 - SPREAD_USD
                r1r2.append(p | dict(out_t=ts, out_px=c, reason="TIME", pnl=pnl))
                open_pos.remove(p)
        for L in list(pending):
            if L["until"] < ts:
                pending.remove(L); continue
            filled = (l <= L["px"]) if L["side"] == "S" else (h >= L["px"])
            if filled and len(open_pos) < K_CAP:
                open_pos.append(dict(side=L["side"], in_px=L["px"], in_t=ts, lvl=L["lvl_px"]))
                done.add(L["key"])
                pending.remove(L)
        if k >= NET5:
            hi3 = max(m1[k - a][2] for a in range(STALL_M1))
            lo3 = min(m1[k - a][3] for a in range(STALL_M1))
            net5 = sum(m1[k - a][4] - m1[k - a][1] for a in range(NET5))
            for L in zones_at(ts):
                key = (L["kind"], round(L["px"], 2))
                if key in done or any(x["key"] == key for x in pending):
                    continue
                wait = ts - L["t_conf"] >= STALL_WAIT_M1 * 60
                if L["kind"] == "H" and wait and hi3 < L["px"] + STALL_TOL and net5 < 0:
                    pending.append(dict(key=key, side="S", px=L["px"] - FADE_PTS, lvl_px=L["px"],
                                         until=ts + LIMIT_TTL_MIN * 60))
                elif L["kind"] == "L" and wait and lo3 > L["px"] - STALL_TOL and net5 > 0:
                    pending.append(dict(key=key, side="B", px=L["px"] + FADE_PTS, lvl_px=L["px"],
                                        until=ts + LIMIT_TTL_MIN * 60))
    ts, o, h, l, c = m1[-1]
    for p in list(open_pos):
        pnl = ((c - p["in_px"]) if p["side"] == "B" else (p["in_px"] - c)) * 2.0 - SPREAD_USD
        r1r2.append(p | dict(out_t=ts, out_px=c, reason="EOD", pnl=pnl))
        open_pos.remove(p)
    return r1r2, blocked, v0_blocked_pnl, len(zones)


def kpi(trades):
    n = len(trades)
    pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return n, pnl, wins


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", action="store_true", help="E6: 12 phiên 02/10→14/10, 2 biến thể G2")
    args = ap.parse_args()
    db = sqlite3.connect(DB)
    ent, ext = load_v0(db)

    if not args.days:
        # ===== pilot 1 ngày 10/14 =====
        T0, T1 = E(2026, 10, 13, 17, 0), E(2026, 10, 14, 10, 30)
        r1r2, blocked, v0_bp, nz = run_replay(db, T0, T1, ent, ext, "A")
        v0_pnl_all = sum(x["pnl"] for x in ext.values())
        bl = [b for b in blocked if b[6] < 0]
        bw = [b for b in blocked if b[6] > 0]
        print(f"M1 zones: {nz} · v0 entries: {len(ent)} · v0 exits dedup: {len(ext)}")
        print(f"G2-LVL(A): CHẶN {len(blocked)} lệnh · PnL loại {v0_bp:+.2f}$ "
              f"(trốn lỗ {sum(b[6] for b in bl):+.2f} · phí win {sum(b[6] for b in bw):+.2f})")
        n, pnl, wins = kpi(r1r2)
        print(f"R1/R2: {n} lệnh · PnL {pnl:+.2f}$ · WR {wins}/{n}")
        print(f"v0 THẬT: {v0_pnl_all:+.2f}$ · COUNTERFACTUAL: {v0_pnl_all - v0_bp + pnl:+.2f}$")
        print("\n=== G2-LVL: lệnh v0 bị chặn ===")
        for pos, side, t, px, lvl, src, p in sorted(blocked, key=lambda r: r[2]):
            tag = "" if pos in ext else " (còn mở)"
            print(f"  {HMS(t)}  v0 {side} @{px:.2f} · nguồn {src} ({lvl:.2f}) · PnL loại {p:+.2f}${tag}")
        print("\n=== R1/R2: lệnh mới ===")
        for t in r1r2:
            print(f"  {HMS(t['in_t'])}  {t['side']} @{t['in_px']:.2f} (zone {t['lvl']:.2f})"
                  f" → {t['reason']} @{t['out_px']:.2f} {HMS(t['out_t'])} · {t['pnl']:+.2f}$")
        return

    # ===== E6: 12 phiên (02/10→14/10, session 04:45+07 → 04:45+07) + tail 14/10 =====
    days = [E(2026, 10, d, 4, 45) for d in range(2, 15)]
    days.append(E(2026, 10, 14, 14, 45))
    report = []
    totals = {"A": [0, 0.0, 0, 0, 0.0, 0.0, 0.0], "B": [0, 0.0, 0, 0, 0.0, 0.0, 0.0]}
    # [n_r1r2, pnl_r1r2, wins, n_blocked, pnl_blocked, avoid_loss, cost_win]
    all_trades = []
    for i in range(len(days) - 1):
        T0, T1 = days[i], days[i + 1]
        label = f"10/{(i + 2):02d}"
        for var in ("A", "B"):
            r1r2, blocked, v0_bp, nz = run_replay(db, T0, T1, ent, ext, var)
            n, pnl, wins = kpi(r1r2)
            all_trades += r1r2
            t = totals[var]
            t[0] += n; t[1] += pnl; t[2] += wins
            t[3] += len(blocked); t[4] += v0_bp
            t[5] += sum(b[6] for b in blocked if b[6] < 0)
            t[6] += sum(b[6] for b in blocked if b[6] > 0)
        print(f"  10/{i+2:02d}: R1R2 {n:>3} lệnh {pnl:+8.2f}$ WR {wins:>2}/{n}")
        report.append(f"  {label}: R1R2 {n:>3} · {pnl:+8.2f}$ · WR {wins:>2}/{n}")
    n, pnl, wins = kpi(all_trades)
    v0_pnl_all = sum(x["pnl"] for x in ext.values())
    print("\n".join(report))
    print(f"\n=== E6 TỔNG KẾT (12 phiên + tail 14/10, proxy m1) ===")
    print(f"R1/R2 (chung): {n} lệnh · PnL {pnl:+.2f}$ · WR {wins}/{n} ({100 * wins / max(1, n):.0f}%)")
    for var in ("A", "B"):
        t = totals[var]
        print(f"G2-{var}: chặn {t[3]} lệnh · PnL loại {t[4]:+.2f}$ "
              f"(trốn lỗ {t[5]:+.2f} / phí win {t[6]:+.2f})")
    print(f"v0 THẬT (13-10→14-10): {v0_pnl_all:+.2f}$ (dedup exit_log)")
    v0_cf_A = v0_pnl_all - totals["A"][4]
    v0_cf_B = v0_pnl_all - totals["B"][4]
    print(f"COUNTERFACTUAL chỉ-cửa-v0 (13-10→14-10): G2-A → {v0_cf_A:+.2f}$ · G2-B → {v0_cf_B:+.2f}$")
    print("(R1R2 12 ngày là KPI độc lập — cộng khi V2 ship, không trộn vào baseline v0 1.5 ngày)")
    with open("logs/replay_lvl_12day.txt", "w") as f:
        f.write("\n".join(report + [""] + [
            f"E6: r1r2={n} pnl={pnl:.2f} WR={wins}/{n}",
            f"G2-A blocked={totals['A'][3]} pnl_removed={totals['A'][4]:.2f} "
            f"(loss_avoided={totals['A'][5]:.2f} win_cost={totals['A'][6]:.2f})",
            f"G2-B blocked={totals['B'][3]} pnl_removed={totals['B'][4]:.2f} "
            f"(loss_avoided={totals['B'][5]:.2f} win_cost={totals['B'][6]:.2f})",
            f"v0_actual={v0_pnl_all:.2f} cf_A={v0_cf_A:.2f} cf_B={v0_cf_B:.2f}"]) + "\n")
    print("[ok] saved → logs/replay_lvl_12day.txt")


if __name__ == "__main__":
    main()
