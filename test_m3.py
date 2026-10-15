"""P2-H M3 (C4) unit tests — in-tick burst gate (sự cố 07:05:01 15/10: 8 fills/1s).

Run: .venv/bin/python test_m3.py   (I/O-free: strategy-only)
Cơ chế: fill root trong tick → _record_root_fill(side, px): (1) _tick_fills (gate in-tick qua
_can_open_new_root) · (2) hủy R-arm cùng chiều < MIN_ROOT_STEP_PTS. Snapshot loop guard
mất `arm in r1r2_arms` (arm đã bị hủy vẫn còn trong snapshot).
"""
import sys
sys.path.insert(0, ".")
from src import config as C
from src.scalp_strategy import ScalpStrategy

WIN = ((0, 1305),)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} :: {detail}")


def mk_strategy(px=4116.5):
    s = ScalpStrategy(C)
    ts = 1792000000
    s.now_ts = ts - (ts // 60) % 1440 * 60 + 700 * 60   # 11:40Z ∈ window (0,1305)
    s.last_px = px
    s.m0_regime = "CREEP"
    return s


def mk_arm(side, px, key, until, lvl_px=None):
    return {"key": key, "side": side, "px": px, "lvl_px": lvl_px if lvl_px is not None else px,
            "ts": 0, "until": until, "touches": 3, "regime": "RANGE"}


print("── P2-H M3 (C4) · IN-TICK BURST GATE ──")

# (a) 3 R-arm CÙNG CHIỀU cách 0.2–0.4pt, giá chạm cả 3 trong 1 tick → chỉ 1 fill
s = mk_strategy()
T = s.now_ts
s.r1r2_arms = [mk_arm("L", 4116.4, "a", T + 9999), mk_arm("L", 4116.6, "b", T + 9999),
               mk_arm("L", 4116.8, "c", T + 9999)]
acts = s.decide([], WIN, C.ROLLOVER_MIN)
arm_ents = [a for a in acts if a.get("arm")]
check("burst: 3 arm cùng chiều → chỉ 1 ENTER trong tick",
      len(arm_ents) == 1 and arm_ents[0]["arm"] == "a", f"n={len(arm_ents)} {arm_ents}")

# (b) arm cùng chiều < 0.35pts của fill → bị HỦY khỏi pending · ≥ step + ngược chiều → GIỮ
s2 = mk_strategy()
T = s2.now_ts
s2.r1r2_arms = [mk_arm("L", 4116.4, "a", T + 9999), mk_arm("L", 4116.6, "b", T + 9999),
                mk_arm("L", 4117.2, "c", T + 9999), mk_arm("S", 4115.0, "d", T + 9999)]
s2.decide([], WIN, C.ROLLOVER_MIN)
left = [a["key"] for a in s2.r1r2_arms]
check("hủy arm: b (0.2pt cùng chiều) khỏi pending", "b" not in left, f"left={left}")
check("giữ arm: c (0.6pt > step) + d (ngược chiều, chưa chạm)", "c" in left and "d" in left, f"left={left}")

# (c) guard remove: arm expired + đã bị _record_root_fill hủy (cùng snapshot) → KHÔNG ValueError
s3 = mk_strategy()
T = s3.now_ts
# a fires @4116.4 → hủy b (4116.5, 0.1pt, cùng chiều) RA KHỎI list · b cũng until=0 (expired)
# → snapshot iteration tới b: nhánh `now >= until` gọi remove() — phải có guard
s3.r1r2_arms = [mk_arm("L", 4116.4, "a", T + 9999), mk_arm("L", 4116.5, "b", 0)]
try:
    acts3 = s3.decide([], WIN, C.ROLLOVER_MIN)
    arm3 = [a for a in acts3 if a.get("arm")]
    check("guard remove: snapshot-canceled+expired → không crash, 1 fill", len(arm3) == 1, f"{acts3}")
except ValueError as e:
    check("guard remove: snapshot-canceled+expired → không crash, 1 fill", False, str(e))

# (d) _tick_fills reset mỗi decide (fills tick 1 không còn ở tick 2)
s4 = mk_strategy()
s4.r1r2_arms = [mk_arm("L", 4116.4, "a", s4.now_ts + 9999)]
s4.decide([], WIN, C.ROLLOVER_MIN)
first = list(s4._tick_fills)
s4._tick_fills = [("L", 9999.9)]            # fake giá carry-over — decide() phải reset
s4.r1r2_arms = [mk_arm("L", 4116.4, "z", s4.now_ts + 9999)]
s4.decide([], WIN, C.ROLLOVER_MIN)
check("reset: _tick_fills không mang state qua tick kế (fake 9999.9 bị xóa)",
      first == [("L", 4116.4)] and s4._tick_fills == [("L", 4116.4)],
      f"tick1={first} tick2={s4._tick_fills}")

# (e) fill L + arm S cùng tick → arm S không bị ảnh hưởng (ngược chiều tự do)
s5 = mk_strategy()
T = s5.now_ts
s5.r1r2_arms = [mk_arm("L", 4116.4, "a", T + 9999), mk_arm("S", 4117.0, "d", T + 9999)]
acts5 = s5.decide([], WIN, C.ROLLOVER_MIN)
arms5 = sorted(a["arm"] for a in acts5 if a.get("arm"))
check("cross-side: L-fill + S-arm chạm → cả 2 ENTER (M3 chỉ chặn CÙNG chiều)",
      arms5 == ["a", "d"], f"{arms5}")

print(f"\nRESULT: {PASS + FAIL} checks · {PASS} pass · {FAIL} fail " + ("✅" if FAIL == 0 else "❌"))
sys.exit(1 if FAIL else 0)
