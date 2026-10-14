"""Round-trip test save_state/load_state (OFFLINE, không mạng) — lệnh 14-10.
Chứng minh: restore cascade từ JSON giữ nguyên levels/fz/arm/momentum."""
import json
import os
import time

from src import config as C
from src.scalp_strategy import ScalpStrategy, SLevel

T0 = 1791900000


def make_strategy() -> ScalpStrategy:
    s = ScalpStrategy(C)
    s.last_px = 4155.816
    s.m1_closes = [(T0 + i * 60, 4150 + i * 0.01) for i in range(30)]
    s.m1_closed = [(T0 + i * 60, 4150 + i * 0.02, 4149 + i * 0.02) for i in range(6)]
    s.m5_closed = [(T0 + i * 300, 4150 + i * 0.1, 4149 + i * 0.1) for i in range(3)]
    s.levels = [
        SLevel("L", 4152.5, T0, True, False, 3, T0 + 60, False),
        SLevel("H", 4158.2, T0, True, True, 1, T0 + 30, False),
        SLevel("L", 4156.7, T0 + 120, True, False, 2, T0 + 240, True),
    ]
    s.lowest_conf_l = 4152.5
    s.highest_conf_h = 4158.2
    s.pb_arm_min, s.pb_arm_side, s.pb_arm_px = 1234, "S", 4156.9
    s.pb_arm_len, s.pb_arm_pc = 2, 1
    s.mom_fire_min, s.mom_fire_count, s.mom_last_candle_min = 1234, 1, 1230
    s.peak_fav = {"4868294378": 4154.74}
    s.fz_tops = {4158.5: [2, 7, False], 4159.0: [1, 7, True]}
    s.fz_bots = {4152.3: [3, 7, False]}
    s.fz_gen = 8
    s._m1_cur_min, s._m1_hi, s._m1_lo = 1235, 4156.0, 4155.1
    return s


def main() -> None:
    s = make_strategy()
    path = "data/state_test.json"
    s.save_state(path)
    raw = json.load(open(path))
    assert raw.get("ts", 0) > 0, "ts missing"
    assert len(raw["levels"]) == 3, "levels lost"

    s2 = ScalpStrategy(C)
    assert s2.load_state(raw), "load_state returned False"

    # levels: dataclass eq (mọi field)
    assert s2.levels == s.levels, f"levels differ:\n{s2.levels}\nvs\n{s.levels}"
    # candles + drift
    assert s2.m1_closes == s.m1_closes, "m1_closes differ"
    assert s2.m1_closed == s.m1_closed, "m1_closed differ"
    assert s2.m5_closed == s.m5_closed, "m5_closed differ"
    # FZ grid (float keys restored đúng kiểu)
    assert s2.fz_tops == s.fz_tops, "fz_tops differ"
    assert s2.fz_bots == s.fz_bots, "fz_bots differ"
    assert all(isinstance(k, float) for k in s2.fz_tops), "fz keys not float"
    assert s2.fz_gen == s.fz_gen
    # momentum / arm
    assert s2.pb_arm_min == 1234 and s2.pb_arm_side == "S" and s2.pb_arm_px == 4156.9
    assert s2.mom_fire_min == 1234 and s2.mom_fire_count == 1
    assert s2.peak_fav == s.peak_fav
    assert s2.lowest_conf_l == 4152.5 and s2.highest_conf_h == 4158.2
    assert s2.last_px == 4155.816
    # drift5m tính được từ m1_closes restore
    assert abs(s2.drift5m() - s.drift5m()) < 1e-9, "drift5m mismatch"
    # idempotent: save→load lần 2
    s3 = ScalpStrategy(C)
    s2.save_state(path)
    s3.load_state(json.load(open(path)))
    assert s3.levels == s.levels and s3.fz_tops == s.fz_tops, "2nd round-trip lost data"
    os.remove(path)
    print(
        "STATE ROUND-TRIP OK · levels=%d fz_tops=%d fz_bots=%d drift5m=%.2f "
        "(m1_closes=%d, m1_closed=%d, m5_closed=%d, peak_fav=%d)"
        % (
            len(s.levels), len(s.fz_tops), len(s.fz_bots), s.drift5m(),
            len(s.m1_closes), len(s.m1_closed), len(s.m5_closed), len(s.peak_fav),
        )
    )


if __name__ == "__main__":
    main()
