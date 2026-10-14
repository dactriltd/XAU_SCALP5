"""MOM1 REPLAY — CHAIRMAn 13-10 18:xx: GIÁ LÊN MUA LÊN · GIÁ XUỐNG BÁN XUỐNG.
Signal = net px_now − close K nến M1 đã khép ≥ +THR (LONG) / ≤ −THR (SHORT).
1 lệnh/M1 candle · K=2 · KHÔNG SL · exit = TP 1.5 | TIME(MOM_TIME_STOP) | ROL.
PnL MỌI lệnh trừ SPREAD_PTS=0.24 (đo log sync Exness 13-10) — audit chân thực.

Chạy: .venv/bin/python _replay_mom.py
"""
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

from src import config as C
from src.scalp_strategy import ScalpStrategy

DB = "/Users/admin/.kimlong_agents/data/kimlong_agents.db"
USD_PER_PT = C.LOT * 100  # 0.02 lot = 2 oz → $2/pt


def mom_cfg(k: int = 3, thr: float = 1.5, tstop: int = 15, windows_all: bool = False,
            fade: bool = False, spread: float = 0.24, policy: str = "NOW",
            entry_mode: str = "EDGE", kctx: int = 2, arm_len: int = 1,
            max_pc: int = 1, strong: float = 0.0,
            fz: str = "OFF", fz_touch: int = 2, fz_band: float = 0.5) -> SimpleNamespace:
    ns = SimpleNamespace(**{kk: getattr(C, kk) for kk in dir(C) if kk.isupper()})
    ns.MODE = "MOM1"
    ns.MOM_K_BARS = k
    ns.MOM_THR_PTS = thr
    ns.MOM_TIME_STOP = tstop
    ns.MOM_FADE_EXIT = fade
    ns.SPREAD_PTS = spread
    ns.MOM_EXIT_POLICY = policy
    ns.MOM_ENTRY = entry_mode
    ns.K_CONTEXT = kctx
    ns.WINDOWS = ((0, C.ROLLOVER_MIN),) if windows_all else C.WINDOWS
    ns.MOM_ARM_LEN = arm_len
    ns.MOM_MAX_PER_CANDLE = max_pc
    ns.MOM_STRONG_PTS = strong
    ns.FZ_MODE = fz
    ns.FZ_MIN_TOUCH = fz_touch
    ns.FZ_BAND_PTS = fz_band
    assert getattr(ns, "FZ_MODE") == fz and getattr(ns, "MOM_STRONG_PTS") == strong, \
        "cfg attr không apply được (SNA semantics)"
    return ns


def replay(rows, cfg):
    s = ScalpStrategy(cfg)
    open_pos = []
    trades = []
    entries = defaultdict(list)   # day -> [entry dict]
    next_id = 1
    cur_day = None
    day_pnl = 0.0
    halted = False
    max_conc = 0
    for ts, o, h, l, c in rows:
        d = ts // 86400
        if d != cur_day:
            cur_day = d
            day_pnl = 0.0
            halted = False
        for dt, px in ((10, o), (25, h), (40, l), (58, c)):
            t = ts + dt
            s.on_tick(t, px)
            acts = s.decide(open_pos, cfg.WINDOWS, cfg.ROLLOVER_MIN)
            for a in acts:
                if a["kind"].startswith("ENTER"):
                    if halted:
                        continue
                    p = {
                        "id": str(next_id),
                        "side": "L" if a["kind"] == "ENTER_LONG" else "S",
                        "entry": a["px"],
                        "entry_ts": t,
                        "anchor": a["anchor"],
                    }
                    next_id += 1
                    open_pos.append(p)
                    max_conc = max(max_conc, len(open_pos))
                    entries[d].append({"kind": p["side"], "entry": a["px"], "t": t,
                                       "min": t // 60, "mom": a.get("drift5m")})
                else:
                    p = next((x for x in open_pos if x["id"] == a["pos_id"]), None)
                    if p is None:
                        continue
                    side = 1 if p["side"] == "L" else -1
                    if a["reason"] == "TP":
                        pnl_pts, exit_px = C.TP_POINTS, p["entry"] + side * C.TP_POINTS
                    else:
                        exit_px = a["px"]
                        pnl_pts = (exit_px - p["entry"]) * side
                    pnl_pts -= cfg.SPREAD_PTS          # spread 1 lượt (entry+exit)
                    pnl_usd = pnl_pts * USD_PER_PT
                    trades.append({"day": d, "kind": p["side"], "reason": a["reason"],
                                   "entry": p["entry"], "exit": exit_px,
                                   "pnl_pts": pnl_pts, "pnl_usd": pnl_usd})
                    day_pnl += pnl_usd
                    open_pos.remove(p)
                    if day_pnl <= -cfg.DAILY_LOSS_STOP:
                        halted = True
    return trades, entries, max_conc


def day_label(d):
    return datetime.fromtimestamp(d * 86400, tz=timezone.utc).strftime("%d-%m")


def report(name, cfg, trades, entries, max_conc, n_days):
    n = len(trades)
    tp = [t for t in trades if t["reason"] == "TP"]
    tot_pts = sum(t["pnl_pts"] for t in trades)
    tot_usd = sum(t["pnl_usd"] for t in trades)
    # anti-spam: >1 entry cùng (day, M1-minute) = vi phạm
    spam = Counter((e["min"],) for es in entries.values() for e in es)
    n_spam = sum(1 for v in spam.values() if v > 1)
    daily = [day_label(d) + ":" + str(len(es)) for d, es in sorted(entries.items()) if es]
    print(f"\n===== {name} (K={cfg.MOM_K_BARS} · THR={cfg.MOM_THR_PTS} · TIME={cfg.MOM_TIME_STOP}′ · "
          f"{cfg.MOM_EXIT_POLICY} · {cfg.MOM_ENTRY} · Kctx={cfg.K_CONTEXT} · "
          f"{'ALLDAYS' if len(cfg.WINDOWS) == 1 else 'SESSION'}) =====")
    print(f"  trades={n} · {n / n_days:.1f}/ngày · WR(TP)={100 * len(tp) / n if n else 0:.0f}% · "
          f"PnL(spread {cfg.SPREAD_PTS})={tot_pts:+.1f}pts={tot_usd:+.2f}$ · avg={tot_pts / n if n else 0:+.3f}pts/lệnh")
    print(f"  exit reasons: {dict(Counter(t['reason'] for t in trades))} · max-concurrent={max_conc} (≤{cfg.K_CONTEXT})")
    print(f"  anti-spam: {n_spam} nến-M1 >1 entry {'❌' if n_spam else '✅'}")
    print(f"  entries/ngày: " + " · ".join(daily))
    last = trades[-4:] if trades else []
    if last:
        print("  4 lệnh cuối: " + " | ".join(
            f"{t['kind']}@{t['entry']:.1f}({t['reason']},{t['pnl_pts']:+.2f})" for t in last))
    return tot_usd, n


def main():
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT ts, open, high, low, close FROM m1_candles "
        "WHERE symbol='XAUUSDm' ORDER BY ts").fetchall()
    db.close()
    n_days = len({r[0] // 86400 for r in rows})
    print(f"m1 bars={len(rows)} · {n_days} ngày · "
          f"{day_label(rows[0][0] // 86400)}→{day_label(rows[-1][0] // 86400)} · USD_PER_PT={USD_PER_PT}")

    variants = [
        ("R0 F3-ref · NOW · K2", mom_cfg(3, 1.5, 15, policy="NOW", kctx=2)),
        ("R1 NOW · K4", mom_cfg(3, 1.5, 15, policy="NOW", kctx=4)),
        ("R2 WAITPOS · K2", mom_cfg(3, 1.5, 15, policy="WAITPOS", kctx=2)),
        ("R3 WAITPOS · K4", mom_cfg(3, 1.5, 15, policy="WAITPOS", kctx=4)),
        ("R4 WAIT · K4", mom_cfg(3, 1.5, 15, policy="WAIT", kctx=4)),
        ("R5 WAITPOS · K4 · PULLBACK", mom_cfg(3, 1.5, 15, policy="WAITPOS", entry_mode="PULLBACK", kctx=4)),
        ("R6 WAIT · K4 · PULLBACK", mom_cfg(3, 1.5, 15, policy="WAIT", entry_mode="PULLBACK", kctx=4)),
        ("R7 WAITPOS · K6", mom_cfg(3, 1.5, 15, policy="WAITPOS", kctx=6)),
    ]
    print("\nCHỌN: PnL (sau spread) cao nhất với trades/14d ≥ 60 (n≥40/2 tuần dễ đạt) + 0 spam + max-conc ≤ 2.")
    for name, cfg in variants:
        t0 = time.time()
        trades, entries, max_conc = replay(rows, cfg)
        report(name, cfg, trades, entries, max_conc, n_days)
        print(f"  (replay {time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
