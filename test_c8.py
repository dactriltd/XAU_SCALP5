"""P2-H3 C8-Unified Live Gate (15/10 11:0x HUMAN-approved · docs/P2-H3 §4.5) unit tests.

Run: .venv/bin/python test_c8.py   (I/O-free: strategy-only, gọi thẳng _can_open_new_root)
Giả lập counterfactual 15/10 (08:41:20→10:09:17): 7/7 rổ lỗ chặn · 0 TP-loss (chạy replay reference).
LƯU Ý composite: M3 (abs<0.35 hai chiều, giữ nguyên) preempt band G1/G2 trước → C8 các gate còn
sống: G3 (span NAKED >1.0) · G4 (Δ<−0.90) · G5 (30s sau leg) · G1/G2 = belt-and-suspenders
(thuận cross-tick/limit-fill khi M3 px-đcision lệch fill — verify live qua KPI iii §6).
"""
import sys
from contextlib import contextmanager
sys.path.insert(0, ".")
from src import config as C
from src.scalp_strategy import ScalpStrategy

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} :: {detail}")


def mk(px, t=1792000000, c8=None):
    s = ScalpStrategy(C)
    s.now_ts = t + 700 * 60        # 11:40Z ∈ window (0, 1305)
    s.last_px = px
    s.m0_regime = "CREEP"
    if c8 is not None:
        C.C8_ENABLE = c8
    return s


def root(pid, side, entry, t, age=100, parent_id=None, leg_type=None):
    p = {"id": pid, "side": side, "entry": entry, "entry_ts": t - age}
    if parent_id:
        p["parent_id"] = parent_id
        p["leg_type"] = leg_type or "HEDGE"
    return p


@contextmanager
def with_c8(on):
    old = C.C8_ENABLE
    C.C8_ENABLE = on
    try:
        yield
    finally:
        C.C8_ENABLE = old


T = 1792000000
print("── P2-H3 C8-Unified · LIVE GATE (G1-G5) ──")

# (a) G3 O2 live-anchor: A3 repro — NAKED L @4146.158, px 4147.576 (Δ +1.418 > 1.0) → CHẶN
s = mk(4147.576, c8=True)
check("G3 block: NAKED-live span +1.418 → chặn (A3 09:19:47, cứu rổ −2.93)",
      s._can_open_new_root("L", [root("4877300602", "L", 4146.158, T)]) is False)

# (b) span ≤ 1.0 → CHO QUA (A2 09:19:01, Δ +0.436, TP +3.07)
s = mk(4146.594, c8=True)
check("span ≤ 1.0 qua gate (A2 +0.436, giữ TP)",
      s._can_open_new_root("L", [root("4877300602", "L", 4146.158, T)]) is True)

# (c) S đối xứng: SHORT chase xuống — NAKED S @4160.500, px 4159.000 (Δ +1.50) → CHẶN
s = mk(4159.000, c8=True)
check("G3 S-symmetric: span +1.50 (chase SHORT xuống) → chặn",
      s._can_open_new_root("S", [root("r1", "S", 4160.500, T)]) is False)

# (d) G1: 0 < Δ < 0.35 (B_0914 09:14:12, Δ +0.287) → CHẶN (M3 abs<0.35 cũng preempt — composite đúng)
s = mk(4145.215, c8=True)
check("G1 fwd-step +0.287 chặn (B_0914, composite M3+C8)",
      s._can_open_new_root("L", [root("4877278376", "L", 4144.928, T)]) is False)

# (e) G2: Δ −0.003 (B_0939 09:39:39, −0.003) chặn · Δ −0.403 (pullback thật, giữ TP) CHO QUA
s = mk(4144.680, c8=True)
check("G2 dup −0.003 chặn (B_0939)",
      s._can_open_new_root("L", [root("4877401991", "L", 4144.683, T)]) is False)
s = mk(4158.700, c8=True)
check("pullback −0.403 ≥ 0.35-band M3 + không chạm G2/G4 → qua (giữ lệnh bắt nhịp lùi)",
      s._can_open_new_root("L", [root("4877515079", "L", 4159.103, T)]) is True)

# (f) G4: Δ −0.969 < −0.90 (B_1000_2 10:00:08, nhồi S khi S-trước âm −0.97) CHẶN ·
#     Δ −0.867 (09:27:28, TP +3.39) CHO QUA
s = mk(4160.164, c8=True)
check("G4 stack −0.969 chặn (B_1000_2, cứu −4.21)",
      s._can_open_new_root("S", [root("4877530139", "S", 4159.195, T)]) is False)
s = mk(4142.836, c8=True)
check("Δ −0.867 không chạm G4 (giữ TP +3.39, 09:27:28)",
      s._can_open_new_root("S", [root("4877345272", "S", 4141.969, T)]) is True)

# (g) G5: 13s/25s sau leg CHẶN (Case D 10:01:01 / B_0844 08:44:28) · 31s+ CHO QUA
for dt, expected, label in ((13, False, "13s (Case D, xóa ind −29.00)"),
                            (25, False, "25s (B_0844)"),
                            (31, True, "31s+ (hết cooldown)")):
    s = mk(4161.000, c8=True)
    s.last_hedge_leg_ts = s.now_ts - dt
    check(f"G5 {label} → {'chặn' if not expected else 'cho qua'}",
          s._can_open_new_root("L", []) is expected)

# (h) G3 NAKED-only: root LOCKED (đã có leg) KHÔNG tính span → cho qua; C8_OFF = parity (case (a) geometry)
s = mk(4147.576, c8=True)
check("G3 NAKED-only: LOCKED-root (có leg) không fire span",
      s._can_open_new_root("L", [root("r2", "L", 4146.158, T),
                                 root("leg2", "S", 4144.90, T, parent_id="r2")]) is True)
with with_c8(False):
    s = mk(4147.576)
    check("C8_ENABLE=False: parity — geometry G3 nhưng M3-pass → cho qua (1 dòng revert)",
          s._can_open_new_root("L", [root("4877300602", "L", 4146.158, T)]) is True)

print(f"\nRESULT: {PASS + FAIL} checks · {PASS} pass · {FAIL} fail " + ("✅" if FAIL == 0 else "❌"))
sys.exit(1 if FAIL else 0)
