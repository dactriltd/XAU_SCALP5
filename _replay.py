"""A/B REPLAY — trigger B (S-neo) trên 15,000 M1 kimlong (11 ngày 28/09→13/10).
Simulate ĐÚNG pipeline decide() của strategy (K gate · windows · exit ladder · daily cap $30).
Mục tiêu: chọn (LADDER_TF, S_BOUNCE_PTS) bằng số — tần suất lệnh + WR + PnL + anti-spam.

Chạy: .venv/bin/python _replay.py
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


def variant_cfg(tf: str, bounce: float) -> SimpleNamespace:
    ns = SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if k.isupper()})
    ns.MODE = "B_SNEO"          # pin B (C.MODE đã mặc định MOM1 từ 13-10 18:xx)
    ns.LADDER_TF = tf
    ns.S_BOUNCE_PTS = bounce
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
                    entries[d].append({"kind": p["side"], "entry": a["px"], "anchor": a["anchor"], "t": t})
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
                    pnl_usd = pnl_pts * USD_PER_PT
                    trades.append({"day": d, "kind": p["side"], "reason": a["reason"],
                                   "entry": p["entry"], "exit": exit_px,
                                   "pnl_pts": pnl_pts, "pnl_usd": pnl_usd})
                    day_pnl += pnl_usd
                    open_pos.remove(p)
                    if day_pnl <= -cfg.DAILY_LOSS_STOP:
                        halted = True
    return trades, entries


def day_label(d):
    return datetime.fromtimestamp(d * 86400, tz=timezone.utc).strftime("%d-%m")


def report(name, cfg, trades, entries, n_days):
    n = len(trades)
    tp = [t for t in trades if t["reason"] == "TP"]
    tot_pts = sum(t["pnl_pts"] for t in trades)
    tot_usd = sum(t["pnl_usd"] for t in trades)
    print(f"\n===== {name} (LADDER_TF={cfg.LADDER_TF} · BOUNCE={cfg.S_BOUNCE_PTS}) =====")
    print(f"  trades={n} · {n / n_days:.1f}/ngày · WR(TP)={100 * len(tp) / n if n else 0:.0f}% · "
          f"PnL={tot_pts:+.1f}pts={tot_usd:+.2f}$ · avg={tot_pts / n if n else 0:+.2f}pts/lệnh")
    print(f"  exit reasons: {dict(Counter(t['reason'] for t in trades))}")
    # anti-spam: 1 S-level (anchor) trên 1 ngày không được > MAX_TOUCH lần entry
    spam = 0
    per_lv = Counter((d, e["kind"], round(e["anchor"], 1)) for d, es in entries.items() for e in es)
    for k, v in per_lv.items():
        if v > cfg.MAX_TOUCH:
            spam += 1
            print(f"  [SPAM] {k} → {v} entry (> {cfg.MAX_TOUCH})")
    print(f"  anti-spam: {spam} level-violation" + (" ✅" if spam == 0 else " ❌"))
    print("  entries/ngày: " + " · ".join(
        f"{day_label(d)}:{len(es)}" for d, es in sorted(entries.items())))
    last = trades[-4:] if trades else []
    if last:
        print("  4 lệnh cuối: " + " | ".join(
            f"{t['kind']}@{t['entry']:.1f}→{t['exit']:.1f}({t['reason']},{t['pnl_pts']:+.1f})" for t in last))


def main():
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT ts, open, high, low, close FROM m1_candles "
        "WHERE symbol='XAUUSDm' ORDER BY ts").fetchall()
    db.close()
    n_days = len({r[0] // 86400 for r in rows})
    print(f"m1 bars={len(rows)} · {n_days} ngày · {day_label(rows[0][0]//86400)}→{day_label(rows[-1][0]//86400)}")

    variants = [
        ("M1 B0.4", variant_cfg("M1", 0.4)),
        ("M1 B0.8", variant_cfg("M1", 0.8)),
        ("M1 B1.5", variant_cfg("M1", 1.5)),
        ("M1 B2.5", variant_cfg("M1", 2.5)),
        ("M5 B0.8", variant_cfg("M5", 0.8)),
        ("M5 B1.5", variant_cfg("M5", 1.5)),
        ("M5 B2.5", variant_cfg("M5", 2.5)),
    ]
    results = []
    for name, cfg in variants:
        t0 = time.time()
        trades, entries = replay(rows, cfg)
        dt = time.time() - t0
        results.append((cfg, trades, entries, dt))
        report(name, cfg, trades, entries, n_days)
        print(f"  (replay {dt:.1f}s)")
    print("\nCHỌN: variant có trades/night ≥ ~3-4 (đủ n≥40 trong 10 phiên) + WR/PnL hợp lý + 0 spam.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
