#!/usr/bin/env python3
"""_chart_px_time.py — BIỂU ĐỒ GIÁ–THỜI GIAN dạng TEXT BOX + sự kiện vào/thoát lệnh của bot.

Nguồn data (thực, không suy diễn):
  - Nến 1m      : DB data/scalp5.db (candles, symbol XAUUSDm, timeframe='1m')
  - Vào lệnh    : entry_log(ts, pos_id, kind, entry, tp, touch, drift5m)
  - Thoát lệnh  : exit_log(ts, pos_id, reason, exit_px, pnl) — DEDUP theo pos_id
                  (spec #16 EXIT_LOG integrity: 1 row/pos_id, giữ ts sớm nhất)

Phương pháp (5 bước):
  1. CỬA SỔ   : [min(ts events) − 15′, max(ts events) + 15′]
  2. LƯỚI     : cột = bucket thời gian (step "nice" tùy cửa sổ), hàng = dải giá (step "nice")
  3. TRACE    : mỗi cột: H=cao nhất, L=thấp nhất, │=thân, ┤=close, ·=cột thiếu nến (broker gap)
  4. SỰ KIỆN  : B=ENTER_LONG, S=ENTER_SHORT, X=exit, ★=≥2 sự kiện trùng 1 ô (event ghi đè trace)
  5. TEXT BOX  : box KPI + box VỊ THẾ (entry→exit pair + PnL) + box SỰ KIỆN (14 dòng/box)

Chạy:  python3 _chart_px_time.py   → in stdout + logs/chart_px_time.txt
"""
import math
import sqlite3
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=7))
DB = "data/scalp5.db"
OUT = "logs/chart_px_time.txt"


def nice_step(raw: float) -> float:
    for n in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50):
        if n >= raw:
            return n
    return 100


def hm(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")


def hms(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M:%S")


def text_box(title: str, lines) -> str:
    W = max([len(title)] + [len(l) for l in lines]) + 4
    out = ["┌─ " + title + "─" * max(0, W - len(title) - 2) + "┐"]
    out += ["│ " + l.ljust(W - 2) + " │" for l in lines]
    out.append("└" + "─" * W + "┘")
    return "\n".join(out)


def load():
    conn = sqlite3.connect(DB)
    ent = {}
    for ts, pos, kind, px, tp, touch, dr in conn.execute(
            "SELECT ts,pos_id,kind,entry,tp,touch,drift5m FROM entry_log"):
        if pos not in ent:
            ent[pos] = dict(ts=ts, kind=kind, px=px, tp=tp, touch=touch, drift5m=dr)
    ext = {}
    raw_exit_rows = 0
    for ts, pos, reason, px, pnl in conn.execute(
            "SELECT ts,pos_id,reason,exit_px,pnl FROM exit_log"):
        raw_exit_rows += 1
        if pos not in ext or ts < ext[pos]["ts"]:  # dedup spec #16
            ext[pos] = dict(ts=ts, reason=reason, px=px, pnl=pnl)
    all_ts = [v["ts"] for v in ent.values()] + [v["ts"] for v in ext.values()]
    t0, t1 = min(all_ts), max(all_ts)
    rows = conn.execute(
        "SELECT timestamp, high, low, close FROM candles "
        "WHERE symbol='XAUUSDm' AND timeframe='1m' AND timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp", (t0, t1)).fetchall()
    return ent, ext, t0, t1, rows, raw_exit_rows


def all_events(ent, ext):
    ev = []
    for pos, e in ent.items():
        ch = "B" if e["kind"] == "ENTER_LONG" else "S"
        ev.append((e["ts"], ch, pos, e["px"],
                   f'{hms(e["ts"])}  {ch}  {e["px"]:.2f}  '
                   f'{"LONG " if ch == "B" else "SHORT"}  tp={e["tp"]:.2f}  '
                   f'touch={e["touch"]}  drift5m={e["drift5m"]:+.2f}  pos={pos}'))
    for pos, x in ext.items():
        s = "+" if (x["pnl"] or 0) >= 0 else ""
        ev.append((x["ts"], "X", pos, x["px"],
                   f'{hms(x["ts"])}  X  {x["px"]:.2f}  {x["reason"]}  '
                   f'pnl={s}{x["pnl"]:.2f}$  pos={pos}'))
    ev.sort(key=lambda r: (r[0], r[1]))
    return ev


def render_chart(ev, candles, t0, t1, bucket_sec, target_rows, title):
    nb = max(1, int(round((t1 - t0) / bucket_sec)))
    stats = {}
    for ts, hi, lo, cl in candles:
        b = min(nb - 1, int((ts - t0) // bucket_sec))
        s = stats.setdefault(b, [hi, lo, cl, 0])
        s[0], s[1], s[2], s[3] = max(s[0], hi), min(s[1], lo), cl, s[3] + 1
    if not stats:
        return text_box(title, ["(không có nến 1m trong cửa sổ)"])
    pmax = max(s[0] for s in stats.values())
    pmin = min(s[1] for s in stats.values())
    step = nice_step((pmax - pmin) / target_rows)
    ptop = math.ceil(pmax / step) * step
    rows = int(round((ptop - pmin) / step)) + 1

    def row_of(px):
        return max(0, min(rows - 1, int(round((ptop - px) / step))))

    grid = [[" "] * nb for _ in range(rows)]
    for b in range(nb):
        if b in stats:
            hi, lo, cl, _ = stats[b]
            hi_r, lo_r, cl_r = row_of(hi), row_of(lo), row_of(cl)
            for r in range(hi_r, lo_r + 1):
                grid[r][b] = "│"
            grid[hi_r][b], grid[lo_r][b] = "H", "L"
            if hi_r < cl_r < lo_r:
                grid[cl_r][b] = "┤"
        else:
            grid[rows // 2][b] = "·"  # gap: broker trả 0 nến (KNOWN-EMPTY-GAP)
    cell_ev = {}
    for ts, ch, pos, px, _ in ev:
        b = max(0, min(nb - 1, int((ts - t0) // bucket_sec)))
        cell_ev.setdefault((b, row_of(px)), []).append(ch)
    for (b, r), chs in cell_ev.items():
        grid[r][b] = chs[0] if len(chs) == 1 else "★"

    lw = max(7, len(f"{ptop:,.2f}"))  # độ rộng nhãn giá (8 nếu giá ≥ 1,000 + 2 số thập phân)
    inner = lw + nb + 3
    k = max(1, math.ceil(rows / 11))
    trow = ("│" + (title if len(title) <= inner else title[: inner - 1] + "…")
            .ljust(inner) + "│")
    out = ["┌" + "─" * inner + "┐",
           trow,
           "├" + "─" * (lw + 2) + "┼" + "─" * nb + "┤"]
    for r in range(rows):
        px = ptop - r * step
        lab = (f"{px:,.2f}" if step < 1 else f"{px:,.0f}") if r % k == 0 else " " * lw
        out.append("│ " + lab.ljust(lw) + " " + "".join(grid[r]) + " │")
    step_cols = max(5, round(nb / 8))
    slots, total = [], 0
    for i in range(0, nb, step_cols):
        if total + step_cols > nb + 1:
            break
        slots.append(hm(t0 + i * bucket_sec).ljust(step_cols))
        total += step_cols
    axis = "".join(slots).ljust(nb + 1)
    out.append("│" + " " * (lw + 2) + axis.ljust(nb + 1) + "│")
    out.append("└" + "─" * (lw + 2) + "┴" + "─" * nb + "┘")
    out.append("  H=high L=low │=thân ┤=close ·=thiếu nến (gap)  "
               "B=long-entry S=short-entry X=exit ★=≥2 trùng ô  ·  mọi giờ = +07")
    return "\n".join(out)


def kpi_box(ent, ext, raw_exit_rows, t0, t1):
    matched = sorted(set(ent) & set(ext), key=lambda p: ent[p]["ts"])
    wins = [ext[p]["pnl"] for p in matched if (ext[p]["pnl"] or 0) > 0]
    losses = [ext[p]["pnl"] for p in matched if (ext[p]["pnl"] or 0) <= 0]
    tot = sum((ext[p]["pnl"] or 0) for p in matched)
    reasons = {}
    for x in ext.values():
        reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    open_pos = [p for p in ent if p not in ext]
    no_entry = [p for p in ext if p not in ent]
    open_shown = ", ".join(open_pos[:8]) + (f" … (+{len(open_pos) - 8})" if len(open_pos) > 8 else "")
    lines = [
        f"Cửa sổ sự kiện   : {hms(t0)} → {hms(t1)}  ({(t1 - t0) / 60:.0f} phút, +07)",
        f"Vào lệnh         : {len(ent)} pos (entry_log)",
        f"Thoát lệnh       : {len(ext)} pos sau dedup  (exit_log raw {raw_exit_rows} row → "
        f"thừa {raw_exit_rows - len(ext)} row trùng, bỏ theo spec #16)",
        f"Position đã pair   : {len(matched)}  |  có entry, exit_log chưa có (còn mở HOẶC exit chưa sync/broker-only): {len(open_pos)}  "
        f"|  exit không có entry (adopt/recover): {len(no_entry)}",
        (f"pos chưa exit      : {open_shown}") if open_shown else "pos chưa exit      : (không có)",
        f"KPI PnL (dedup)  : total {tot:+.2f}$  |  win {len(wins)} / loss {len(losses)}  "
        f"WR {100 * len(wins) / max(1, len(matched)):.1f}%",
        "Reason thoát       : " + " · ".join(f"{k}×{v}" for k, v in
                                              sorted(reasons.items(), key=lambda kv: -kv[1])),
    ]
    return text_box("KPI · exit_log dedup theo pos_id (spec #16) · tz +07", lines)


def pos_box(ent, ext):
    matched = sorted(set(ent) & set(ext), key=lambda p: ent[p]["ts"])
    lines = []
    for i, p in enumerate(matched, 1):
        e, x = ent[p], ext[p]
        side = "B" if e["kind"] == "ENTER_LONG" else "S"
        dur = int((x["ts"] - e["ts"]) / 60)
        lines.append(f'#{i:2d} {hms(e["ts"])} {side} @ {e["px"]:8.2f}  →  '
                     f'{hms(x["ts"])} {x["reason"]:<11s} @ {x["px"]:8.2f}  '
                     f'{x["pnl"]:+8.2f}$  ({dur:3d}m)  pos={p}')
    return text_box(f"VỊ THẾ (entry_log → exit_log, pair theo pos_id, {len(matched)} lệnh)", lines)


def ev_boxes(ev, group=14):
    out = []
    n = len(ev)
    for i in range(0, n, group):
        chunk = ev[i:i + group]
        out.append(text_box(f"SỰ KIỆN raw (dòng {i + 1}–{i + len(chunk)} / {n})",
                            [l[4] for l in chunk]))
    return "\n\n".join(out)


def main():
    ent, ext, t0, t1, candles, raw_exit_rows = load()
    ev = all_events(ent, ext)

    parts = ["# XAU_SCALP5 — BIỂU ĐỒ GIÁ–THỜI GIAN TEXT BOX (data/scalp5.db) · "
             f"generated {datetime.now(TZ).strftime('%Y-%m-%d %H:%M +07')}"]
    parts.append(kpi_box(ent, ext, raw_exit_rows, t0, t1))

    p0, p1 = t0 - 900, t1 + 900
    full_bucket = next(b for b in (300, 600, 900, 1800, 3600)
                       if (p1 - p0) / b <= 72)
    parts.append(render_chart(
        ev, candles, p0, p1, full_bucket, 28,
        f"XAUUSDm · 1m · {hm(p0)}–{hm(p1)} +07 · bucket {full_bucket // 60}m · {len(ev)} events"))

    z1 = max(v["ts"] for v in ext.values())
    z0 = z1 - 3600
    zcandles = [c for c in candles if z0 <= c[0] <= z1]
    zev = [e for e in ev if z0 <= e[0] <= z1]
    parts.append(render_chart(
        zev, zcandles, z0, z1, 60, 28,
        f"XAUUSDm · 1m · {hm(z0)}–{hm(z1)} +07 · bucket 1m · {len(zev)} events (zoom 60′)"))

    parts.append(pos_box(ent, ext))
    parts.append(ev_boxes(ev))

    text = "\n\n".join(parts) + "\n"
    with open(OUT, "w") as f:
        f.write(text)
    print(text)
    print(f"\n[ok] full report saved → {OUT}")


if __name__ == "__main__":
    main()
