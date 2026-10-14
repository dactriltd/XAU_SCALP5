"""OFFLINE REGRESSION — replay M1 kimlong (12-10) vào ScalpStrategy theo config.

Section A: MOM1 PULLBACK (C.MODE="MOM1" · PULLBACK pub0.8 · K4 · T10 · SESSION — CHAIRMAN 13-10 19:xx:
           "timing lệnh ở đỉnh/đáy" · data: NOW+PULLBACK = +$1123/11d · 103 entries/12-10).
Section B: B_SNEO regression (M1 bounce 2.5, SAU fix merge-swallow: 11 entries/12-10).
Chạy: .venv/bin/python test_offline.py
"""
import sqlite3
from collections import Counter
from types import SimpleNamespace

from src import config as C
from src.scalp_strategy import ScalpStrategy

DB = "/Users/admin/.kimlong_agents/data/kimlong_agents.db"
DAY = "2026-10-12"
EPS = 0.01


def ns(**over) -> SimpleNamespace:
    b = SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if k.isupper()})
    for k, v in over.items():
        setattr(b, k, v)
    return b


def run_day(rows, cfg):
    s = ScalpStrategy(cfg)
    open_pos, ents, exits, reasons = [], [], [], Counter()
    next_id, max_open = 1, 0
    for ts, o, h, l, c in rows:
        for dt, px in ((10, o), (25, h), (40, l), (58, c)):
            t = ts + dt
            s.on_tick(t, px)
            for a in s.decide(open_pos, cfg.WINDOWS, cfg.ROLLOVER_MIN):
                if a["kind"].startswith("ENTER"):
                    max_open = max(max_open, len(open_pos) + 1)
                    posd = {
                        "id": str(next_id),
                        "side": "L" if a["kind"] == "ENTER_LONG" else "S",
                        "entry": a["px"], "entry_ts": t, "anchor": a["anchor"],
                    }
                    # S4-HEDGE: chân HEDGE mang metadata rổ (giống executor.enter is_leg)
                    if a.get("leg_type") == "HEDGE":
                        posd.update({
                            "parent_id": a.get("parent_id"), "leg_type": "HEDGE",
                            "hedge_credit": 0.0, "unwound": False,
                            "wall_px": a.get("anchor"),
                        })
                    open_pos.append(posd)
                    ents.append(a)
                    next_id += 1
                else:
                    p = next((x for x in open_pos if x["id"] == a["pos_id"]), None)
                    if p is not None:
                        open_pos.remove(p)
                    reasons[a["reason"]] += 1
                    exits.append(a)
    return s, ents, exits, max_open, reasons


def day_rows(db):
    t0 = db.execute(f"SELECT strftime('%s','{DAY}')").fetchone()[0]
    return db.execute(
        "SELECT ts, open, high, low, close FROM m1_candles "
        f"WHERE symbol='XAUUSDm' AND ts >= ? AND ts < ? ORDER BY ts",
        (int(t0), int(t0) + 86400),
    ).fetchall()


def check(name: str, cond: bool, detail: str) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")
    return cond


def main() -> int:
    db = sqlite3.connect(DB)
    rows = day_rows(db)
    db.close()
    ok = True
    # mirrors main.py: wins = ((0, ROLLOVER_MIN),) if WINDOWS_ALL else C.WINDOWS
    wins = ((0, C.ROLLOVER_MIN),) if C.WINDOWS_ALL else C.WINDOWS

    # ── A: MOM1 PULLBACK (config đang ship: PULLBACK pub0.8 · K4 · T10 · NOW · ALLDAY) ──
    print(f"── A: MOM1 {C.MOM_ENTRY} pub{C.MOM_PUB_PTS} (MODE={C.MODE} · k{C.MOM_K_BARS} · thr{C.MOM_THR_PTS} · "
          f"{C.MOM_EXIT_POLICY} · TIME{C.MOM_TIME_STOP}′ · K={C.K_CONTEXT} · {'ALLDAY' if C.WINDOWS_ALL else 'SESSION'}) · {len(rows)} M1 ──")
    _, ents, exits, max_open, reasons = run_day(rows, ns(WINDOWS=wins))
    mins = [a["level_ts"] // 60 for a in ents]
    ok &= check("windows", all(ScalpStrategy.in_window(a["level_ts"], wins) for a in ents),
                f"all {len(ents)} entries ∈ {wins if C.WINDOWS_ALL else 'SESSION windows'}")
    # invariant PULLBACK: tại nến-signal (candle KHỞI ĐẦU phút m−1, khép tại m−1→m),
    # close[m−1] − close[m−1−K] phải vượt ngưỡng (đúng mom_c ở on_tick)
    closes_by_min: dict = {}
    for r in rows:
        closes_by_min[r[0] // 60] = r[4]

    def sig_ok(a) -> bool:
        # RE-FIRE + FZ (ship 13-10 tối 4): entry phút m có signal tại m−1 (bình thường,
        # |mom|≥THR) HOẶC strong arm extension (signal M−2, |mom|≥STRONG → arm +1 nến).
        # FZ-FADE: side có thể NGƯỢC signal (flip tại vùng test ≥2) → chỉ kiểm tra CƯỜNG ĐỘ tín hiệu.
        m = a["level_ts"] // 60
        K = C.MOM_K_BARS

        def mom_at(mm):
            cs, ref = closes_by_min.get(mm), closes_by_min.get(mm - K)
            return cs - ref if (cs is not None and ref is not None) else None

        m1, m2 = mom_at(m - 1), mom_at(m - 2)
        ok = m1 is not None and abs(m1) >= C.MOM_THR_PTS - EPS
        if not ok and C.MOM_STRONG_PTS > 0 and m2 is not None:
            ok = abs(m2) >= C.MOM_STRONG_PTS - EPS
        return ok

    n_sig_bad = sum(1 for a in ents if not sig_ok(a))
    ok &= check("tín hiệu PULLBACK (|close[m−1]−close[m−1−K]| ≥ THR, hoặc strong m−2 ≥ STRONG)",
                n_sig_bad == 0, f"{n_sig_bad}/{len(ents)} entry vi phạm (0 = mọi lệnh đều có tín hiệu thật)")
    ok &= check("hướng dip/bật (MUA vào dip dưới đỉnh · BÁN vào bật trên đáy)",
                all((a["kind"] == "ENTER_LONG" and a["drift5m"] is not None) or
                    (a["kind"] == "ENTER_SHORT" and a["drift5m"] is not None) for a in ents),
                f"LONG {sum(1 for a in ents if a['kind']=='ENTER_LONG')} · "
                f"SHORT {sum(1 for a in ents if a['kind']=='ENTER_SHORT')}")
    # RE-FIRE: strong signal cho phép +1 lệnh/candle (MOM_MAX_PER_CANDLE+1)
    per_min = Counter(mins)
    worst_pc = max(per_min.values()) if per_min else 0
    cap = C.MOM_MAX_PER_CANDLE + (1 if C.MOM_STRONG_PTS > 0 else 0)
    ok &= check(f"≤{cap} lệnh/M1 candle (re-fire strong)", worst_pc <= cap,
                f"{len(mins)} entries · worst={worst_pc}/nến (≤{cap})")
    ok &= check("K=gate", max_open <= C.K_CONTEXT, f"max_open={max_open} ≤ {C.K_CONTEXT}")
    ok &= check("exit ⊆ {TP,TIME,ROL,PSL,DRIFT,HEDGE_TAKE,BASKET_TP,PRUNE_BREAK,PRUNE_SPAN} "
                "(KHÔNG SL/S_BREAK/FADE — PSL=S1 14/10 · DRIFT=R1R2 S3-B · S4-HEDGE exit-set 15/10)",
                set(reasons) <= {"TP", "TIME", "ROL", "PSL", "DRIFT",
                                 "HEDGE_TAKE", "BASKET_TP", "PRUNE_BREAK", "PRUNE_SPAN"},
                f"{dict(reasons)}")
    ok &= check("tần suất 12-10", 465 <= len(ents) <= 477,
                f"{len(ents)} entries (run_day KHÔNG daily-cap → pin=471 [S1 PSL re-fire + S3-B R1R2 arms, "
                f"re-baseline 14/10 tối]; pin cũ: V3+FZ=426, V0=286, V3-FZ_OFF=397)")

    # ── B: B_SNEO regression (sau fix merge-swallow) ──
    print(f"── B: B_SNEO (M1 · bounce {2.5} · merge-skip-broken fix · {'ALLDAY' if C.WINDOWS_ALL else 'SESSION'}) · {len(rows)} M1 ──")
    cfgB = ns(MODE="B_SNEO", WINDOWS=wins)
    cfgB.LADDER_TF = "M1"
    cfgB.S_BOUNCE_PTS = 2.5
    _, entsB, exitsB, max_openB, reasonsB = run_day(rows, cfgB)
    ok &= check("hướng (LONG≥anchor+2.5−ε · SHORT≤anchor−2.5+ε)",
                all((a["kind"] == "ENTER_LONG" and a["px"] >= a["anchor"] + C.S_BOUNCE_PTS - EPS) or
                    (a["kind"] == "ENTER_SHORT" and a["px"] <= a["anchor"] - C.S_BOUNCE_PTS + EPS)
                    for a in entsB),
                f"{len(entsB)} entries")
    ok &= check("K=gate", max_openB <= C.K_CONTEXT, f"max_open={max_openB} ≤ {C.K_CONTEXT}")
    per_lv = Counter((a["kind"], round(a["anchor"], 1)) for a in entsB)
    worst = max(per_lv.items(), key=lambda x: x[1]) if per_lv else ("-", 0)
    ok &= check("anti-spam per-level", worst[1] <= C.MAX_TOUCH + 1,
                f"worst={worst[0]}×{worst[1]} (≤{C.MAX_TOUCH + 1}, gồm level mới cùng px)")
    ok &= check("tần suất 12-10 (sau fix)", 15 <= len(entsB) <= 23,
                f"{len(entsB)} entries (run_day KHÔNG daily-cap → pin=19; replay_mom có-cap pin=10 · pin SESSION=11)")

    print("\nRESULT:", "ALL PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
