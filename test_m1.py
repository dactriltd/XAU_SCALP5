"""P2-H M1 (C2) unit tests — ORPHAN_CLEANUP · prune-guard · exact-relink (executor._tag).

Run: .venv/bin/python test_m1.py   (I/O-free: strategy + pure functions)
"""
import sys
sys.path.insert(0, ".")
from src import config as C
from src.scalp_strategy import ScalpStrategy
from src.scalp_executor import ScalpExecutor

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


def mk_strategy():
    s = ScalpStrategy(C)
    # now_ts tại phút UTC 700 (11:40Z) ∈ window (0,1305) · ngoài ROL
    ts = 1792000000
    s.now_ts = ts - (ts // 60) % 1440 * 60 + 700 * 60
    s.last_px = 4141.0
    s.m0_regime = "CREEP"
    return s


print("── P2-H M1 (C2) · ORPHAN / PRUNE-GUARD / TAG ──")

# (a) Chân HEDGE mồ côi (root không còn trên sàn) → EXIT ORPHAN_CLEANUP
s = mk_strategy()
leg = {"id": "LEG1", "side": "S", "entry": 4117.0, "entry_ts": s.now_ts - 600,
       "parent_id": "ROOT_X", "leg_type": "HEDGE"}
acts = s.decide([leg], WIN, C.ROLLOVER_MIN)
check("orphan: leg mồ côi → EXIT ORPHAN_CLEANUP",
      any(a["kind"] == "EXIT" and a.get("reason") == "ORPHAN_CLEANUP" and a["pos_id"] == "LEG1" for a in acts),
      f"acts={acts}")

# (b) open_pos rỗng (RPC stall) → KHÔNG có ORPHAN_CLEANUP (list trống không kết luận được)
s = mk_strategy()
acts = s.decide([], WIN, C.ROLLOVER_MIN)
check("orphan-guard: open_pos rỗng → 0 ORPHAN_CLEANUP",
      not any(a.get("reason") == "ORPHAN_CLEANUP" for a in acts), f"acts={acts}")

# (c) root CÒN TRÊN SÀN → không orphan (máy rổ quản lý, không close lẻ)
s = mk_strategy()
root = {"id": "ROOT_X", "side": "L", "entry": 4118.277, "entry_ts": s.now_ts - 900}
leg2 = dict(leg, id="LEG2", parent_id="ROOT_X")
acts = s.decide([root, leg2], WIN, C.ROLLOVER_MIN)
check("no-orphan: root còn → leg không bị close lẻ",
      not any(a.get("reason") == "ORPHAN_CLEANUP" for a in acts), f"acts={acts}")

# (d) prune-guard: root vắng + seen_ts FRESH (<grace) → GIỮ registry
s = mk_strategy()
s.hedge_baskets = {"ROOT_X": {"wall_px": None, "seen_ts": s.now_ts}}
other = {"id": "R2", "side": "L", "entry": 4140.0, "entry_ts": s.now_ts - 10}
s.decide([other], WIN, C.ROLLOVER_MIN)
check("prune-guard: fresh (<45s) → GIỮ", "ROOT_X" in s.hedge_baskets, f"{list(s.hedge_baskets)}")

# (e) prune-guard: root vắng + seen_ts STALE (≥grace) → XÓA
s = mk_strategy()
s.hedge_baskets = {"ROOT_X": {"wall_px": None, "seen_ts": s.now_ts - 3600}}
s.decide([other], WIN, C.ROLLOVER_MIN)
check("prune: stale (≥45s) → XÓA", "ROOT_X" not in s.hedge_baskets, f"{list(s.hedge_baskets)}")

# (f) prune-guard: open_pos RỖNG → tuyệt đối không wipe (chuỗi sự cố 02:25)
s = mk_strategy()
s.hedge_baskets = {"ROOT_X": {"wall_px": None, "seen_ts": s.now_ts - 3600}}
s.decide([], WIN, C.ROLLOVER_MIN)
check("prune-guard: open_pos rỗng → GIỮ TẤT CẢ", "ROOT_X" in s.hedge_baskets, f"{list(s.hedge_baskets)}")

# (g) executor._tag: exact-relink từ broker comment
check("tag: leg mới SCALP5-HEDGE:<rid>",
      ScalpExecutor._tag({"comment": "SCALP5-HEDGE:123"}) == {"leg_type": "HEDGE", "parent_id": "123"})
check("tag: leg cũ không-id (fallback)",
      ScalpExecutor._tag({"comment": "SCALP5-HEDGE"}) == {"leg_type": "HEDGE", "parent_id": ""})
check("tag: root SCALP5 → không tag", ScalpExecutor._tag({"comment": "SCALP5"}) == {})
check("tag: no comment → không tag", ScalpExecutor._tag({}) == {})

print(f"\nRESULT: {PASS + FAIL} checks · {PASS} pass · {FAIL} fail " + ("✅" if FAIL == 0 else "❌"))
sys.exit(1 if FAIL else 0)
