"""_smoke_lvl.py — SMOKE OFFLINE (DB READ-ONLY) cho src/lvl.py (S3-A · C-A + fix H-only owner).

Chạy: .venv/bin/python _smoke_lvl.py
In 5 dòng + ghi logs/lvl_smoke.txt (evidence cho verifier / STATE.md / gate §14.3).
KHÔNG viết DB: mở file:...?mode=ro · engine _persist tự skip (lvl.py L137-138).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src import lvl  # noqa: E402

DB = "data/scalp5.db"


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    eng = lvl.rebuild_from_candles(conn, "XAUUSDm")
    zones = eng.zones
    last_ts = eng.bars[-1][0]

    n_strong = sum(1 for z in zones.values() if z["strong"])
    n_dead = sum(1 for z in zones.values() if z["dead_ts"] is not None)
    n_dead_l = sum(1 for z in zones.values() if z["dead_ts"] is not None and z["kind"] == "L")
    l1 = (f"[1] rebuild {lvl.LVL_REBUILD_M1} nến m1 → zones={len(zones)} · strong={n_strong} · "
          f"dead={n_dead} (H-only · dead_L={n_dead_l} {'✓' if n_dead_l == 0 else '✗ PHẢI =0'}) · "
          f"persist={'skip(readonly)' if eng._readonly else 'WRITE'}")

    # [2][3] G2-LVL S: thời điểm GẦN NHẤT có H-zone strong·alive (giá chạy ~8pts/10h → last-ts thường hết zone)
    now_case, hz = None, None
    for t in [b[0] for b in eng.bars]:  # tăng dần
        zs = lvl.strong_zones("S", t)
        if zs:
            now_case, hz = t, zs[0]
    if hz:
        px_block = round(hz["px"] - 1.0, 2)  # trong band G2LVL_PTS=2.0 → kỳ vọng True
        px_out = round(hz["px"] - 2.5, 2)     # ngoài band (>2.0) → kỳ vọng False
        r2, r3 = lvl.g2_blocked("S", px_block, now_case), lvl.g2_blocked("S", px_out, now_case)
        l2 = (f"[2] G2 S (now={now_case}): H-zone {hz['px']:.3f} touches={hz['touches']} "
              f"t_conf={hz['t_conf']} dead_ts={hz['dead_ts']} · px={px_block}(=zone-1.0) "
              f"→ g2_blocked={r2} {'✓' if r2 else '✗ FAIL (kỳ vọng True)'}")
        l3 = f"[3] G2 S ngoài band: px={px_out}(=zone-2.5 >2.0) → g2_blocked={r3} (kỳ vọng False)"
    else:
        l2, l3 = "[2] G2: không có H-zone strong·alive trong cửa sổ — SKIP", "[3] SKIP"

    ex = lvl.extreme15(last_ts)
    l4 = (f"[4] extreme15 (last={last_ts}): high={ex[0]:.3f}@ts={ex[1]} · low={ex[2]:.3f}@ts={ex[3]} "
          f"(cửa sổ 15 nến m1 đã đóng)" if ex else "[4] extreme15: None (<15 nến)")

    nb, nh = len(lvl.strong_zones("B", last_ts)), len(lvl.strong_zones("S", last_ts))
    l5 = (f"[5] L mirror: B-strong-alive@last={nb} · H-strong-alive@last={nh} · conn mode=ro · "
          f"zones in-memory={len(zones)}")

    lines = [l1, l2, l3, l4, l5]
    out = Path("logs/lvl_smoke.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not (n_dead_l == 0 and (hz is None or ("✗" not in l2 and "✗" not in l3))):
        print("[SMOKE] FAIL — xem ✗ ở trên", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
