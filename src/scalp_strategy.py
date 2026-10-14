"""XAU_SCALP5 STRATEGY — 5 DÒNG QUY TẮC, tick-driven, KHÔNG backtest, KHÔNG hindsight.

1. TRIGGER B (S-neo, CHAIRMAN 13-10 tối): drift có HƯỚNG theo cấu trúc:
              MUA = S_ĐÁY chạm T1-T2 + giá BẬT LÊN ≥$S_BOUNCE_PTS từ đáy (từ dưới lên)
              BÁN = S_ĐỈNH chạm T1-T2 + giá TỤT ≥$S_BOUNCE_PTS từ đỉnh (từ trên xuống)
              (drift5m 5' ròng px_now − close_M1[-5] chỉ còn dùng cho EXIT-flip rule)
2. MUA:   trigger MUA trên S_ĐÁY CÒN SỐNG (confirmed, T1-T2, chưa broken) → ENTER_LONG
3. BÁN:   trigger BÁN trên S_ĐỈNH CÒN SỐNG → ENTER_SHORT
4. TP:    1.5 pts (broker-side) · KHÔNG SL
5. RA:    TP | drift5m flip về 0 (chỉ khi P&L<0) | S-CHAIN BREAK (S mới confirmed dưới/đánh S đang giữ)
           | 15' TIME | ROL 21:45Z

S-LADDER: LADDER_TF "M5" (swings ±2 nến M5, confirm sau 10') | "M1" (swings ±2 nến M1,
scale 1/5: confirm sau 1' — CHAIRMAN 13-10 tối: M5 'quá thô' cho TP 1.5pts).
XÁC NHẬN LIVE (không cần giá tương lai): (a) giá hồi ≥$s_bounce khỏi S (b) s_conf_min trôi qua
TOUCH: ±s_touch_tol, cách nhau ≥s_touch_sep · T3+ = S KIỆT (chặn)

MODE "MOM1" (CHAIRMAN 13-10 18:xx): GIÁ LÊN MUA LÊN · GIÁ XUỐNG BÁN XUỐNG (theo momentum M1):
  signal = net px_now − close cách K nến M1 (MOM_K_BARS) ≥ +THR = MUA · ≤ −THR = BÁN
  vào-rapid (1 lệnh/M1 candle), RA-NHANH: TP 1.5 | TIME MOM_TIME_STOP | ROL · KHÔNG SL ·
  spread 0.24pts/lượt đã audit trong replay (data: net5 persistence ≈ 0 → chọn TIME stop bằng số)
"""
import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

# S3-B V2: LVL M1 ladder + G2-LVL/EXT15 (spec §14) — engine global (rebuild boot + on_m1_close ở main)
try:
    from src import lvl as _lvl
except ImportError:  # src/ làm cwd (thói quen module cũ, parity src/lvl.py)
    import lvl as _lvl  # type: ignore


@dataclass
class SLevel:
    kind: str          # 'L' | 'H'
    px: float
    ts: int            # unix sec của nến M5 form
    confirmed: bool = False
    broken: bool = False
    touches: int = 0
    last_touch: int = 0
    consumed: bool = False   # đã dùng vào lệnh (1 context = 1 lệnh)


class ScalpStrategy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last_px: Optional[float] = None
        self.now_ts: int = 0
        self.m1_closes: list = []        # [(ts, close)] giữ 30 (cho DRIFT5m)
        self.m1_cur: Optional[list] = None     # [ts, hi, lo, px_last]
        self.m1_closed: list = []        # [(ts, hi, lo)] giữ 60 (cho M1 ladder)
        self.m5_closed: list = []        # [(ts, hi, lo)] giữ 48 (cho M5 ladder)
        self.m5_cur: Optional[list] = None
        self.levels: List[SLevel] = []
        self.lowest_conf_l: Optional[float] = None
        self.highest_conf_h: Optional[float] = None
        self.mom_last_candle_min: int = -1  # MOM1: phút M1 đã fire entry (1 lệnh/nến, chống re-fire)
        # MOM1 CHAIRMAN 19:xx: trailing ratchet + PULLBACK entry (timing đỉnh/đáy)
        self.peak_fav: Dict[str, float] = {}  # pos_id → đỉnh lãi thuận (L: max px · S: min px)
        self.pb_arm_min: int = -1             # phút M1 đang armed pullback entry (−1 = không armed)
        self.pb_arm_side: str = ""           # "L" | "S"
        self.pb_arm_px: float = 0.0          # mức dip/bật (đỉnh nến −0.5 cho L · đáy nến +0.5 cho S)
        self.pb_arm_len: int = 1             # RE-FIRE: arm hiệu lực N nến (mạnh = +1)
        self.pb_arm_pc: int = 1             # RE-FIRE: tối đa N lệnh/candle cho arm này (mạnh = +1)
        self.mom_fire_min: int = -1          # phút M1 hiện đang fire (reset counter khi đổi nến)
        self.mom_fire_count: int = 0        # số lệnh đã fire trong nến hiện (gate re-fire)
        # FZ-GRID (CHAIRMAN tối 3 "vùng test ≥2 chưa break"): mức 0.25pts — top: nến nào high chạm
        # (±0.3), đếm touches; closed > lvl+1.0 = broken (phá vỡ, hết fade) · gần 240 nến
        self.fz_tops: Dict[float, list] = {}   # lvl → [touches, gen_seen, broken]
        self.fz_bots: Dict[float, list] = {}
        self.fz_gen: int = 0
        self._m1_cur_min: int = -1
        self._m1_hi: float = 0.0
        self._m1_lo: float = 0.0
        # ── V2 S3-B: R1/R2 stall-fade arms + M0 regime + DRIFT-FLIP (spec §14 / §10) ──
        self.r1r2_arms: List[dict] = []    # limit arm pending: (key=(kind,px,day_utc), side, px=limit, lvl_px, until, ts, regime)
        self.r1r2_done: set = set()        # keys đã MUA (row 18: 1 lệnh/zone/ngày/hướng — day trong key → live strict, replay E6 = parity key không-day)
        self.m0_regime: str = "CREEP"       # tag M0 đang hiệu lực (IMPULSE/V-REV/RANGE/CREEP)
        self.m0_cand: str = ""              # candidate tag (hysteresis proxy m1)
        self.m0_cand_n: int = 0             # nến m1 liên tiếp cùng candidate
        self.m0_drift_sign: int = 0         # sign(drift5m) nến trước (cho V-REV "VỪA LẬT")
        self.m1_ohlcv: list = []            # [(ts,o,h,l,c)] m1 ĐÃ KHÉP giữ 30 — M0 scalars + EXT15 (2 nến C≥O)
        self._df_count: Dict[str, int] = {}  # pos_id → số m1-close liên tiếp drift-adverse (R-pnL<0) (DRIFT-FLIP m1-proxy)
        self._df_last_min: int = -1         # phút m1 đã update _df_count (guard 1 lần/nến)
        # S4-HEDGE (15/10): registry rổ hedge (root_id → {wall_px, wall_peak_px, leg_ids, unwound, hedge_credit})
        # — shadow state persistence cho metadata position (main re-attach sau adopt() StreamStalled restart)
        self.hedge_baskets: Dict[str, dict] = {}
        # TF S-ladder: "M5" (gốc) | "M1" (CHAIRMAN 13-10 tối — scale 1/5, xem S1_* config)
        self.ladder_tf: str = getattr(cfg, "LADDER_TF", "M5")
        if self.ladder_tf == "M1":
            (self.s_bounce, self.s_conf_min, self.s_merge,
             self.s_touch_tol, self.s_touch_sep, self.s_chain_break) = (
                cfg.S1_CONFIRM_BOUNCE, cfg.S1_CONFIRM_MINS, cfg.S1_MERGE,
                cfg.S1_TOUCH_TOL, cfg.S1_TOUCH_SEP_MIN, cfg.S1_CHAIN_BREAK)
        else:
            (self.s_bounce, self.s_conf_min, self.s_merge,
             self.s_touch_tol, self.s_touch_sep, self.s_chain_break) = (
                cfg.S_CONFIRM_BOUNCE, cfg.S_CONFIRM_MINS, cfg.S_MERGE,
                cfg.S_TOUCH_TOL, cfg.S_TOUCH_SEP_MIN, cfg.S_CHAIN_BREAK)

    # ───────────────────── STATE PERSISTENCE (14-10: JSON snapshot boot) ─────────────────────
    def save_state(self, path: str) -> None:
        """Lưu cascade state vận hành (ladder/touches/fz/arm/momentum) → JSON.
        Gọi ở: HB 5' · trước StreamStalled · shutdown (SIGTERM/stale)."""
        data = {
            "ts": int(time.time()),
            "last_px": self.last_px,
            "m1_closes": [list(x) for x in self.m1_closes],
            "m1_closed": [list(x) for x in self.m1_closed],
            "m5_closed": [list(x) for x in self.m5_closed],
            "levels": [
                [lv.kind, lv.px, lv.ts, lv.confirmed, lv.broken, lv.touches, lv.last_touch, lv.consumed]
                for lv in self.levels
            ],
            "lowest_conf_l": self.lowest_conf_l,
            "highest_conf_h": self.highest_conf_h,
            "pb_arm_min": self.pb_arm_min,
            "pb_arm_side": self.pb_arm_side,
            "pb_arm_px": self.pb_arm_px,
            "pb_arm_len": self.pb_arm_len,
            "pb_arm_pc": self.pb_arm_pc,
            "mom_fire_min": self.mom_fire_min,
            "mom_fire_count": self.mom_fire_count,
            "mom_last_candle_min": self.mom_last_candle_min,
            "peak_fav": self.peak_fav,
            "fz_tops": {str(k): v for k, v in self.fz_tops.items()},
            "fz_bots": {str(k): v for k, v in self.fz_bots.items()},
            "fz_gen": self.fz_gen,
            "_m1_cur_min": self._m1_cur_min,
            "_m1_hi": self._m1_hi,
            "_m1_lo": self._m1_lo,
            # S3-B: R1/R2 arms pending + M0 state + DRIFT-FLIP counters (recovery khi main.py restart)
            "r1r2_arms": [[list(a["key"]), a["side"], a["px"], a["lvl_px"], a["until"], a["ts"],
                            a.get("regime", ""), a.get("touches", 0)] for a in self.r1r2_arms],
            "r1r2_done": [list(k) for k in self.r1r2_done],
            "m0_regime": self.m0_regime,
            "m0_cand": self.m0_cand,
            "m0_cand_n": self.m0_cand_n,
            "m0_drift_sign": self.m0_drift_sign,
            "m1_ohlcv": [list(x) for x in self.m1_ohlcv],
            "df_count": {str(k): v for k, v in self._df_count.items()},
            "df_last_min": self._df_last_min,
            # S4-HEDGE: rổ hedge (restore sau StreamStalled — main re-attach vào adopted positions)
            "hedge_baskets": {
                str(rid): dict(
                    wall_px=rec.get("wall_px"),
                    wall_peak_px=rec.get("wall_peak_px"),
                    leg_ids=list(rec.get("leg_ids", [])),
                    unwound=bool(rec.get("unwound", False)),
                    hedge_credit=float(rec.get("hedge_credit", 0.0)),
                )
                for rid, rec in self.hedge_baskets.items()
            },
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def load_state(self, data: dict) -> bool:
        """Khôi phục cascade từ snapshot (JSON). m1_cur/m5_cur/now_ts = None/0
        (rebuild từ tick live; gate now_ts=0 ở main.py giữ nguyên)."""
        if not data:
            return False
        self.last_px = data.get("last_px")
        self.m1_closes = [tuple(x) for x in data.get("m1_closes", [])]
        self.m1_closed = [tuple(x) for x in data.get("m1_closed", [])]
        self.m5_closed = [tuple(x) for x in data.get("m5_closed", [])]
        self.levels = [
            SLevel(kind=r[0], px=r[1], ts=r[2], confirmed=r[3],
                   broken=r[4], touches=r[5], last_touch=r[6], consumed=r[7])
            for r in data.get("levels", [])
        ]
        self.lowest_conf_l = data.get("lowest_conf_l")
        self.highest_conf_h = data.get("highest_conf_h")
        self.pb_arm_min = data.get("pb_arm_min", -1)
        self.pb_arm_side = data.get("pb_arm_side", "")
        self.pb_arm_px = data.get("pb_arm_px", 0.0)
        self.pb_arm_len = data.get("pb_arm_len", 1)
        self.pb_arm_pc = data.get("pb_arm_pc", 1)
        self.mom_fire_min = data.get("mom_fire_min", -1)
        self.mom_fire_count = data.get("mom_fire_count", 0)
        self.mom_last_candle_min = data.get("mom_last_candle_min", -1)
        self.peak_fav = data.get("peak_fav", {}) or {}
        self.fz_tops = {float(k): v for k, v in data.get("fz_tops", {}).items()}
        self.fz_bots = {float(k): v for k, v in data.get("fz_bots", {}).items()}
        self.fz_gen = data.get("fz_gen", 0)
        self._m1_cur_min = data.get("_m1_cur_min", -1)
        self._m1_hi = data.get("_m1_hi", 0.0)
        self._m1_lo = data.get("_m1_lo", 0.0)
        # S3-B (snapshot cũ thiếu keys → default an toàn, load_state tolerates):
        self.r1r2_arms = [
            dict(key=tuple(r[0]), side=r[1], px=r[2], lvl_px=r[3], until=r[4], ts=r[5],
                 regime=r[6] if len(r) > 6 else "", touches=r[7] if len(r) > 7 else 0)
            for r in data.get("r1r2_arms", [])
        ]
        self.r1r2_done = {tuple(r) for r in data.get("r1r2_done", [])}
        self.m0_regime = data.get("m0_regime", "CREEP")
        self.m0_cand = data.get("m0_cand", "")
        self.m0_cand_n = data.get("m0_cand_n", 0)
        self.m0_drift_sign = data.get("m0_drift_sign", 0)
        self.m1_ohlcv = [tuple(x) for x in data.get("m1_ohlcv", [])]
        self._df_count = {int(k): v for k, v in data.get("df_count", {}).items()}
        self._df_last_min = data.get("df_last_min", -1)
        # S4-HEDGE (snapshot cũ thiếu key → default rỗng, load_state tolerant):
        self.hedge_baskets = {
            str(rid): dict(
                wall_px=rec.get("wall_px"),
                wall_peak_px=rec.get("wall_peak_px"),
                leg_ids=list(rec.get("leg_ids", [])),
                unwound=bool(rec.get("unwound", False)),
                hedge_credit=float(rec.get("hedge_credit", 0.0)),
            )
            for rid, rec in (data.get("hedge_baskets") or {}).items()
        }
        return True

    # ─────────────────────────── TICK FEED ───────────────────────────
    def on_tick(self, ts_sec: int, px: float) -> None:
        c = self.cfg
        self.now_ts, self.last_px = ts_sec, px
        # M1 (cho DRIFT5m + M1 ladder)
        m1_ts = ts_sec - ts_sec % 60
        if self.m1_cur is None:
            self.m1_cur = [m1_ts, px, px, px]
        elif m1_ts != self.m1_cur[0]:
            cts, chi, clo, clpx = self.m1_cur
            self.m1_closes.append((cts, clpx))
            self.m1_closes = self.m1_closes[-30:]
            if self.ladder_tf == "M1":
                self.m1_closed.append((cts, chi, clo))
                self.m1_closed = self.m1_closed[-60:]
                if len(self.m1_closed) >= 5:
                    self._close_m1_fractal()
            # MOM1 PULLBACK (CHAIRMAN 19:xx "timing lệnh ở đỉnh/đáy"): tín hiệu TẠI CLOSE NẾN →
            # "armed" dip (đỉnh nến −0.5 cho MUA / đáy nến +0.5 cho BÁN) — KHÔNG đuổi đỉnh, chờ dip
            # RE-FIRE (CHAIRMAN tối 2 "trend tốt thì refire"): tín hiệu MẠNH (|net3|≥MOM_STRONG_PTS)
            # → arm dài hơn (MOM_ARM_LEN+1 nến) & cho phép MOM_MAX_PER_CANDLE+1 lệnh/candle (pyramid)
            # FZ (CHAIRMAN tối 3 "vùng test ≥2 chưa break → lệnh ngược, hấp thụ quán tính → bật lại"):
            #   nến tín hiệu chạm H-zone (đỉnh đã test ≥FZ_MIN_TOUCH, chưa broken) → MUA-BỊ-ĐẢO thành BÁN
            #   nến tín hiệu chạm L-zone (đáy đã test ≥2) → BÁN-BỊ-ĐẢO thành MUA (FADE) · hoặc hủy arm (SKIP)
            if (getattr(c, "MODE", "B_SNEO") == "MOM1"
                    and getattr(c, "MOM_ENTRY", "EDGE") == "PULLBACK"
                    and len(self.m1_closes) > c.MOM_K_BARS):
                mom_c = clpx - self.m1_closes[-(c.MOM_K_BARS + 1)][1]
                strong = getattr(c, "MOM_STRONG_PTS", 0) > 0 and abs(mom_c) >= c.MOM_STRONG_PTS
                arm_len = getattr(c, "MOM_ARM_LEN", 1) + (1 if strong else 0)
                arm_pc = getattr(c, "MOM_MAX_PER_CANDLE", 1) + (1 if strong else 0)
                fz = getattr(c, "FZ_MODE", "OFF")
                min_touch = getattr(c, "FZ_MIN_TOUCH", 2)
                band = getattr(c, "FZ_BAND_PTS", 0.5)

                def _zone_hit(zkind: str, zpx: float) -> bool:
                    d = self.fz_tops if zkind == "H" else self.fz_bots
                    return any(e[0] >= min_touch and not e[2] and abs(lvl - zpx) <= band
                               for lvl, e in d.items())

                arm_side = ""
                arm_px = 0.0
                if mom_c >= c.MOM_THR_PTS:
                    arm_side, arm_px = "L", round(chi - c.MOM_PUB_PTS, 3)
                    if fz and _zone_hit("H", chi):          # đỉnh nến chạm H-zone đã test ≥2 → hấp thụ quán tính
                        if fz == "FADE":
                            arm_side, arm_px = "S", round(clo + c.MOM_PUB_PTS, 3)   # lệnh ngược: bán vào bật
                        else:
                            arm_side = ""                    # SKIP: bỏ lệnh tại vùng debounce này
                elif mom_c <= -c.MOM_THR_PTS:
                    arm_side, arm_px = "S", round(clo + c.MOM_PUB_PTS, 3)
                    if fz and _zone_hit("L", clo):          # đáy nến chạm L-zone đã test ≥2
                        if fz == "FADE":
                            arm_side, arm_px = "L", round(chi - c.MOM_PUB_PTS, 3)   # lệnh ngược: mua vào hắt
                        else:
                            arm_side = ""
                if arm_side:
                    self.pb_arm_min, self.pb_arm_side, self.pb_arm_px = (m1_ts // 60), arm_side, arm_px
                    self.pb_arm_len, self.pb_arm_pc = arm_len, arm_pc
            # FZ grid (CHAIRMAN tối 3): update đếm-test cho nến vừa close (SAU khi tính tín hiệu
            #  → không lookahead): mức lưới 0.25pts, touch = số nến M1 test mức đó, broken = close vượt 1.0pts
            self.fz_gen += 1
            g = getattr(c, "FZ_GRID_PTS", 0.25)
            recent = getattr(c, "FZ_RECENT", 240)
            brk = getattr(c, "FZ_BREAK_PTS", 1.0)
            for ref, d, brk_test in ((chi, self.fz_tops, lambda k: clpx > k + brk),
                                     (clo, self.fz_bots, lambda k: clpx < k - brk)):
                lvl = round(round(ref / g) * g, 3)
                e = d.get(lvl)
                if e is None:
                    d[lvl] = [1, self.fz_gen, False]
                else:
                    e[0] += 1
                    e[1] = self.fz_gen
                stale = [k for k, v in d.items() if v[1] < self.fz_gen - recent]
                for k in stale:
                    del d[k]
                for k, e2 in d.items():
                    if not e2[2] and brk_test(k):
                        e2[2] = True
            self.m1_cur = [m1_ts, px, px, px]
        else:
            self.m1_cur[1] = max(self.m1_cur[1], px)
            self.m1_cur[2] = min(self.m1_cur[2], px)
            self.m1_cur[3] = px
        # M5 (cho S-ladder M5)
        if self.ladder_tf == "M5":
            m5_ts = ts_sec - ts_sec % 300
            if self.m5_cur is None:
                self.m5_cur = [m5_ts, px, px]
            elif m5_ts != self.m5_cur[0]:
                self._close_m5()
            else:
                self.m5_cur[1] = max(self.m5_cur[1], px)
                self.m5_cur[2] = min(self.m5_cur[2], px)
        self._maintain_levels()

    def _close_m1_fractal(self) -> None:
        """M1 fractal: nến M1 cách đây 2 nến có lo/hi ngoài ±2 nến kế bên = swing (±2 M1)."""
        w = self.m1_closed[-5:]
        cand = w[2]
        others_hi = [w[j][1] for j in (0, 1, 3, 4)]
        others_lo = [w[j][2] for j in (0, 1, 3, 4)]
        if cand[2] < min(others_lo):
            self._new_level("L", cand[2], cand[0])
        if cand[1] > max(others_hi):
            self._new_level("H", cand[1], cand[0])

    def _close_m5(self) -> None:
        ts, hi, lo = self.m5_cur
        self.m5_closed.append((ts, hi, lo))
        self.m5_closed = self.m5_closed[-48:]
        self.m5_cur = None
        if len(self.m5_closed) >= 5:
            w = self.m5_closed[-5:]
            cand = w[2]  # ±2 nến M5 confirm
            others_hi = [w[j][1] for j in (0, 1, 3, 4)]
            others_lo = [w[j][2] for j in (0, 1, 3, 4)]
            if cand[2] < min(others_lo):
                self._new_level("L", cand[2], cand[0])
            if cand[1] > max(others_hi):
                self._new_level("H", cand[1], cand[0])

    def _new_level(self, kind: str, px: float, ts: int) -> None:
        for lv in self.levels:
            if lv.kind == kind and not lv.broken and (
                (kind == "L" and px < lv.px) or (kind == "H" and px > lv.px)
            ):
                lv.broken = True        # S mới xuyên S cũ = S-CHAIN BREAK
        # 13-10 18:xx: merge CHỈ với S chưa broken — S cũ vừa broken thì S MỚI phải vào
        # (bug merge-swallow: fractal L 4179.4/4179.7 merge vào L 4179.9 ĐÃ broken → tier L rỗng,
        #  bot không có S nào để MUA cả chiều)
        last = next((lv for lv in reversed(self.levels) if lv.kind == kind and not lv.broken), None)
        if last and abs(px - last.px) < self.s_merge:
            return                      # cùng một mức (merge)
        self.levels.append(SLevel(kind, px, ts))
        self.levels = self.levels[-60:]

    def _maintain_levels(self) -> None:
        for lv in self.levels:
            if lv.broken:
                continue
            if not lv.confirmed:
                ok = (
                    (lv.kind == "L" and self.last_px >= lv.px + self.s_bounce)
                    or (lv.kind == "H" and self.last_px <= lv.px - self.s_bounce)
                    or (self.now_ts - lv.ts >= self.s_conf_min * 60)
                )
                if ok:
                    lv.confirmed = True
            # broken: giá xuyên qua S
            if (lv.kind == "L" and self.last_px < lv.px - self.s_chain_break) or (
                lv.kind == "H" and self.last_px > lv.px + self.s_chain_break
            ):
                lv.broken = True
                lv.consumed = False
                continue
            # touch count (±tol, tách S_TOUCH_SEP)
            at = (
                (lv.kind == "L" and self.last_px <= lv.px + self.s_touch_tol)
                or (lv.kind == "H" and self.last_px >= lv.px - self.s_touch_tol)
            )
            if at and self.now_ts - lv.last_touch >= self.s_touch_sep * 60:
                lv.touches += 1
                lv.last_touch = self.now_ts
            # TRIGGER B: entry xảy ra ở CÁCH S $2.5 (bounce) → re-arm consumed chỉ khi
            # giá VỀ LẠI S (vòng chạm mới), KHÔNG phải khi rời S (tránh re-fire mỗi tick)
            if at and lv.touches > 0:
                lv.consumed = False
        ls = [lv.px for lv in self.levels if lv.kind == "L" and lv.confirmed and not lv.broken]
        hs = [lv.px for lv in self.levels if lv.kind == "H" and lv.confirmed and not lv.broken]
        self.lowest_conf_l = min(ls) if ls else None
        self.highest_conf_h = max(hs) if hs else None

    # ─────────────────────── WARMUP (candles lịch sử → state) ───────────────────────
    def seed_m5(self, bars: list) -> int:
        """Replay nến M5 lịch sử [(ts, o, h, l, c)] vào ladder (cùng cách offline-test).
        Mỗi nến = 4 tick giả (o@+10s, h@+25s, l@+40s, c@+58s) → M5 hi/lo đúng."""
        n = 0
        for ts, o, h, l, c in bars:
            for dt, px in ((10, o), (25, h), (40, l), (58, c)):
                self.on_tick(ts + dt, px)
            n += 1
        return n

    def seed_m1(self, closes: list) -> int:
        """M1 closes [(ts, close)] gần nhất → drift5m deque (KHÔNG replay vào ladder
        để tránh double-count touches với seed_m5). Reset m1_cur để tick live build lại
        sạch (seed_m5 qua on_tick có thể đã nhuốm m1_cur)."""
        self.m1_closes = list(closes)[-30:]
        self.m1_cur = None
        return len(self.m1_closes)

    def seed_m1_bars(self, bars: list) -> int:
        """Replay nến M1 lịch sử [(ts, o, h, l, c)] vào M1 ladder + drift5m
        (cùng 4 tick/nến như seed_m5). Dùng khi LADDER_TF='M1'."""
        n = 0
        for ts, o, h, l, c in bars:
            for dt, px in ((10, o), (25, h), (40, l), (58, c)):
                self.on_tick(ts + dt, px)
            n += 1
        return n

    # ─────────────────────────── STATE ───────────────────────────
    def drift5m(self) -> float:
        """DRIFT5m = ROLLING 5 NẾN M1 (quyết định CHAIRMAN):
        px_now − close_M1 cách 5 nến (m1_closes[-5]). KHÔNG phải TF M5 — M5 chỉ cho S-ladder.
        Ngưỡng ±$2.5 lấy từ phân bố net-5' (P90 +$3.16) trên n=15,000 M1."""
        if self.last_px is not None and len(self.m1_closes) >= 6:
            return self.last_px - self.m1_closes[-5][1]
        return 0.0

    def mode(self) -> Optional[str]:
        d = self.drift5m()
        if d > self.cfg.DRIFT5M_BUY:
            return "BUY"
        if d < self.cfg.DRIFT5M_SELL:
            return "SELL"
        return None

    @staticmethod
    def in_window(ts_sec: int, windows) -> bool:
        m = (ts_sec // 60) % 1440
        return any(a <= m < b for a, b in windows)

    def mom_net(self) -> float:
        """MOM1 (CHAIRMAN 13-10 18:xx): net px_now − close của M1 cách K nến ĐÃ KHÉP
        (K = cfg.MOM_K_BARS). >0 = giá LÊN · <0 = giá XUỐNG. Không cần giá tương lai
        (close[-K] đã khép, last_px = tick live)."""
        k = getattr(self.cfg, "MOM_K_BARS", 3)
        if self.last_px is not None and len(self.m1_closes) >= k:
            return self.last_px - self.m1_closes[-k][1]
        return 0.0

    @staticmethod
    def in_rollover(ts_sec: int, rol_min: int) -> bool:
        m = (ts_sec // 60) % 1440
        return m >= rol_min

    def _break_exit(self, p: dict, pnl_pts: float) -> bool:
        """BREAK-EXIT (S1 14/10, mirror spec rev 6.1 #3): lệnh LỖ thoát khi giá phá S-confirmed NGỊCH.
        LONG → có L confirmed-LOWEST (chưa broken) và giá xuyên DƯỚI nó ± s_chain_break.
        SHORT → có H confirmed-HIGHEST (chưa broken) và giá xuyên TRÊN nó ± s_chain_break.
        Lệnh lãi (pnl_pts ≥ 0) KHÔNG bao giờ → TP/RAIL (WAIT/WAITPOS) xử lý.
        lowest/highest_conf_* được _maintain_levels() cập nhật MỖI tick (live, không lookahead)."""
        if pnl_pts >= 0:
            return False
        if p["side"] == "L" and self.lowest_conf_l is not None:
            return self.last_px < self.lowest_conf_l - self.s_chain_break
        if p["side"] == "S" and self.highest_conf_h is not None:
            return self.last_px > self.highest_conf_h + self.s_chain_break
        return False

    # ─────────────────────── V2 S3-B: G2-LVL · M0 REGIME · R1/R2 STALL-FADE · DRIFT-FLIP ───────────────────────
    def _safe_zones(self, side: str, now: int) -> List[dict]:
        """Zone strong·alive của lvl engine (S→H · B→L). Engine chưa ready/exception → [] (fail-open)."""
        try:
            return _lvl.strong_zones(side, now)
        except Exception:
            return []

    def _g2_block(self, side: str) -> bool:
        """S3-B G2-LVL variant A (spec §14 row 21 · E6 keep-A): CHẶN CỨNG entry v0.
        - NHÁNH LVL: S block nếu px trong G2LVL_PTS DƯỚI H-zone strong·alive (lvl.g2_blocked —
          KHÔNG cần điều kiện nến, bằng chứng cứng) · B mirror.
        - NHÁNH EXT15 (bằng chứng nhẹ, giữ 2-nến theo spec): extreme 15 m1 + 2 nến m1 đóng gần
          nhất chạy NGƯỢC entry (S: C≥O · B: C≤O) và px trong G2LVL_PTS của cực → block.
        ⚠ engine lvl dùng COUNTER CUMULATIVE (S3-A) → main PHẢI advance engine trước khi gọi
        (boot rebuild_from_candles + on_m1_close mỗi nến). Engine rỗng → không block (fail-open,
        log ở main)."""
        if self.last_px is None or self.now_ts == 0:
            return False
        px, now = self.last_px, self.now_ts
        try:
            if _lvl.g2_blocked(side, px, now):
                return True
            # EXT15 — 2 nến m1 ĐÃ KHÉP gần nhất (parity _replay_lvl L139: nến idx & idx−1, C≥O/C≤O)
            ex = _lvl.extreme15(now)          # (ex_h, ts_h, ex_l, ts_l) — 15 nến m1 ĐÃ KHÉP (lvl engine)
            if ex is not None and len(self.m1_ohlcv) >= 2:
                a, b = self.m1_ohlcv[-2], self.m1_ohlcv[-1]
                g = getattr(self.cfg, "G2LVL_PTS", 2.0)
                if side == "S" and b[4] >= b[1] and a[4] >= a[1] and 0 <= ex[0] - px <= g:
                    return True
                if side == "B" and b[4] <= b[1] and a[4] <= a[1] and 0 <= px - ex[2] <= g:
                    return True
        except Exception:
            return False
        return False

    def _m0_hyst_candles(self) -> int:
        """M0_HYST_TICKS=120 tick (spec: 120 tick = 2 tick-phút). ASSUMPTION m1-proxy
        (ghi chú task S3-B): 120 tick ≈ 2 NẾN M1 → hysteresis đổi tag = 2 nến m1 liên tiếp
        cùng candidate (trừ V-REV — tag sự kiện 1 nến, hysteresis làm nó vĩnh viễn không fire
        → đọc bảo thủ: V-REV hiệu lực ngay khi candidate đúng, xem report)."""
        return max(1, round(getattr(self.cfg, "M0_HYST_TICKS", 120) / 60))

    def _m0_snap(self, tag: str, speed: float, form: float, age: float, fz: int) -> dict:
        return dict(tag=tag,
                    side=("up" if self.m0_drift_sign > 0 else "down" if self.m0_drift_sign < 0 else ""),
                    speed=round(speed, 3), form=round(form, 3), age=round(age, 1),
                    fz_touches=fz, m1_candles=len(self.m1_ohlcv))

    def m0_on_m1_close(self, ts: int, o: float, h: float, l: float, c_: float):
        """S3-B M0 regime DETECTOR m1-proxy (spec §10.1/10.2) — main gọi MỖI m1 close,
        SAU lvl.on_m1_close (cùng thời điểm). Trả (tag_hiệu_lực, snap).
        snap = None → tag KHÔNG đổi → không write regime_log (DDL §2.2).

        ASSUMPTIONS m1-proxy (spec đơn vị = tick-phút; replay/live đo trên nến m1):
        - speed = |close_k − close_{k−5}| / 5 (drift5m tại close, thay tick px)
        - form_ratio = Σ|C−O|/Σ(H−L) 5 nến (nến doji H=L → form=0 → CREEP, bảo thủ)
        - extreme_age = số nến m1 đến cực 15-candle gần nhất (lvl engine), threshold M0_EXT_AGE nến
        - FZ touches ≥ 2 := có zone strong (touches ≥ FZ_MIN_TOUCH) alive (proxy grid FZ — note)
        - thứ tự tag = thứ tự liệt kê §10.2 (IMPULSE → V-REV → RANGE → CREEP; first-match,
          ambiguous khi chồng điều kiện → đọc bảo thủ, note report)"""
        c = self.cfg
        self.m1_ohlcv.append((ts, o, h, l, c_))
        self.m1_ohlcv = self.m1_ohlcv[-30:]
        m0_now = ts + 60
        speed = 0.0
        drift_sign = 0
        if len(self.m1_ohlcv) >= 6:
            d5 = self.m1_ohlcv[-1][4] - self.m1_ohlcv[-6][4]
            speed = abs(d5) / 5.0
            drift_sign = 1 if d5 > 0 else (-1 if d5 < 0 else 0)
        form = 0.0
        if len(self.m1_ohlcv) >= 5:
            win = self.m1_ohlcv[-5:]
            sd = sum(abs(w[4] - w[1]) for w in win)
            rng = sum(w[2] - w[3] for w in win)
            form = sd / rng if rng > 0 else 0.0
        age = 99.0
        try:
            ex = _lvl.extreme15(m0_now)
            if ex is not None:
                age = min(m0_now - ex[1], m0_now - ex[3]) / 60.0
        except Exception:
            pass
        fz = len(self._safe_zones("S", m0_now)) + len(self._safe_zones("B", m0_now))
        imp_th = getattr(c, "M0_SPEED_IMP", 0.5)
        range_th = getattr(c, "M0_SPEED_RANGE", 0.25)
        form_th = getattr(c, "M0_FORM", 0.5)
        age_th = getattr(c, "M0_EXT_AGE", 5)
        min_touch = getattr(c, "FZ_MIN_TOUCH", 2)
        flip = drift_sign != 0 and drift_sign != self.m0_drift_sign
        cand = "CREEP"
        if speed >= imp_th and form >= form_th:
            cand = "IMPULSE"
        elif flip and age < age_th and speed >= imp_th:
            cand = "V-REV"
        elif speed < range_th and fz >= min_touch:
            cand = "RANGE"
        self.m0_drift_sign = drift_sign
        snap = None
        if cand == self.m0_regime:
            self.m0_cand, self.m0_cand_n = "", 0
        elif cand == "V-REV":
            if self.m0_regime != "V-REV":          # V-REV = tag sự kiện (1 nến) → hiệu lực NGAY
                self.m0_regime = cand
                snap = self._m0_snap(cand, speed, form, age, fz)
            self.m0_cand, self.m0_cand_n = "", 0
        elif cand == self.m0_cand:
            self.m0_cand_n += 1
            if self.m0_cand_n >= self._m0_hyst_candles():
                self.m0_regime = cand
                snap = self._m0_snap(cand, speed, form, age, fz)
                self.m0_cand, self.m0_cand_n = "", 0
        else:
            self.m0_cand, self.m0_cand_n = cand, 1
        return self.m0_regime, snap

    def r1r2_arm_scan(self, n_open: int = 0) -> List[dict]:
        """S3-B R1/R2 STALL-FADE arms (spec §14 row 19/20) — main gọi MỖI m1 close
        (sau m0_on_m1_close; n_open = số vị thế mở — cap K_CONTEXT kiểm tra lúc FILL trong decide).
        R1 STALL-TOP: H-zone strong·alive + 3 nến m1 kế không phá P+STALL_TOL + net5(C−O) < 0
                     + ≥ STALL_WAIT_M1' sau t_conf → arm S-LIMIT @ P−FADE_PTS (TTL LIMIT_TTL')
        R2 STALL-BOTTOM mirror → arm B-LIMIT @ P+FADE_PTS.
        M0 GATE: regime = IMPULSE → KHÔNG arm (spec §14.3 "10/12 = R1/R2 punish khi trend-impulse").
        Fill proxy: tick (live: giá chạm limit) · m1 close (replay: wick nến ≤/≥ limit, TTL)."""
        c = self.cfg
        if len(self.m1_ohlcv) < 5:
            return []
        now = self.m1_ohlcv[-1][0] + 60            # m1 close time
        if self.m0_regime == "IMPULSE":            # M0 gate (block trong IMPULSE)
            return []
        stall_n = getattr(c, "STALL_M1", 3)
        tol = getattr(c, "STALL_TOL_PTS", 0.25)    # "phá" = vượt mức ±0.25 (E6 STALL_TOL; không có trong config → default)
        wait_min = getattr(c, "STALL_WAIT_M1", 3)  # stall ≥ 3′ sau t_conf (E6 STALL_WAIT_M1)
        fade = getattr(c, "FADE_PTS", 2.5)
        ttl = int(getattr(c, "LIMIT_TTL", 15)) * 60
        tail = self.m1_ohlcv[-stall_n:]
        hi3 = max(w[2] for w in tail)
        lo3 = min(w[3] for w in tail)
        net5 = sum(w[4] - w[1] for w in self.m1_ohlcv[-5:])
        today = now // 86400
        new_arms: List[dict] = []
        for z in self._safe_zones("S", now):       # H-zones → R1 (S-LIMIT)
            key = ("H", round(z["px"], 2), today)
            if key in self.r1r2_done or any(a["key"] == key for a in self.r1r2_arms):
                continue                            # row 18: 1 lệnh/zone/ngày/hướng (done) · 1 arm pending
            if (now - z["t_conf"] >= wait_min * 60 and hi3 < z["px"] + tol and net5 < 0):
                a = dict(key=key, side="S", px=round(z["px"] - fade, 3), lvl_px=z["px"],
                         until=now + ttl, ts=now, regime=self.m0_regime,
                         touches=z.get("touches", 0))
                self.r1r2_arms.append(a)
                new_arms.append(a)
        for z in self._safe_zones("B", now):       # L-zones → R2 (B-LIMIT) mirror
            key = ("L", round(z["px"], 2), today)
            if key in self.r1r2_done or any(a["key"] == key for a in self.r1r2_arms):
                continue
            if (now - z["t_conf"] >= wait_min * 60 and lo3 > z["px"] - tol and net5 > 0):
                a = dict(key=key, side="B", px=round(z["px"] + fade, 3), lvl_px=z["px"],
                         until=now + ttl, ts=now, regime=self.m0_regime,
                         touches=z.get("touches", 0))
                self.r1r2_arms.append(a)
                new_arms.append(a)
        self.r1r2_arms = [a for a in self.r1r2_arms if now < a["until"]]   # dọn arm hết hạn
        self.r1r2_done = {k for k in self.r1r2_done if k[2] >= today - 1}  # giữ 2 ngày (prune)
        return new_arms

    def _df_update_counts(self, open_pos: List[dict]) -> None:
        """S3-B DRIFT-FLIP m1-proxy (spec rev6 #4 → m1 theo task): MỖI m1-close, count nến liên tiếp
        drift adverse (drift = close_k − close_{k−5}, DƯA TRÊN CLOSE — assumption proxy) khi PnL<0
        (pts tại close). Threshold = DRIFT_FLIP_TICKMIN=2 (tick-phút → proxy 2 NẾN m1 liên tiếp).
        Chỉ áp R-positions (lệnh R1/R2, exit 4-lớp)."""
        if len(self.m1_closes) < 6:
            for p in open_pos:
                if p.get("r1r2"):
                    self._df_count[p["id"]] = 0
            return
        d5 = self.m1_closes[-1][1] - self.m1_closes[-6][1]
        cpx = self.m1_closes[-1][1]
        for p in open_pos:
            if not p.get("r1r2"):
                continue
            pts = (cpx - p["entry"]) if p["side"] == "L" else (p["entry"] - cpx)
            adv = (d5 < 0) if p["side"] == "L" else (d5 > 0)
            self._df_count[p["id"]] = (self._df_count.get(p["id"], 0) + 1) if (adv and pts < 0) else 0
        live = {p["id"] for p in open_pos}
        for pid in list(self._df_count):
            if pid not in live:
                del self._df_count[pid]

    # ─────────────────────── S4-HEDGE: ORCHESTRATOR + HEDGE BASKET (15/10) ───────────────────────
    def _can_open_new_root(self, side: str, open_pos: list) -> bool:
        """S4 UNIFIED ORCHESTRATOR — điều kiện MẠNH BẮT BUỘC trước mọi lệnh ROOT
        (MOM1 v0 + R1/R2), chống bắn chùm:
        - HEDGE_ENABLE=False (baseline): giữ hành vi cũ len(open)<K_CONTEXT → regression 100% (Gate 2).
        - HEDGE_ENABLE=True: có chân HEDGE mở / root đang UNWOUND → False (tập trung xử lý rổ);
          roots ≥ MAX_ROOT_POSITIONS → False (chừa slot HEDGE trong K_CONTEXT);
          từng root: giãn cách ≥ MIN_ROOT_GAP_SEC · giá cách ≥ MIN_ROOT_STEP_PTS ·
          bồi lệnh cùng hướng CHỈ khi lệnh cũ đã lãi ≥ +0.5pts.
        (Chân HEDGE do _manage_hedge_basket phát — KHÔNG qua gate này.)"""
        c = self.cfg
        if not getattr(c, "HEDGE_ENABLE", False):
            return len(open_pos) < c.K_CONTEXT
        if any(p.get("leg_type") == "HEDGE" or p.get("unwound") is True for p in open_pos):
            return False
        roots = [p for p in open_pos if not p.get("parent_id")]
        if len(roots) >= getattr(c, "MAX_ROOT_POSITIONS", 2):
            return False
        gap = getattr(c, "MIN_ROOT_GAP_SEC", 20)
        step = getattr(c, "MIN_ROOT_STEP_PTS", 1.0)
        for r in roots:
            if self.now_ts - r.get("entry_ts", 0) < gap:
                return False
            if abs(self.last_px - r["entry"]) < step:
                return False                       # chặn triệt để lỗi 2 lệnh cách 0.01–0.24pts
            if r.get("side") == side:
                r_pts = (self.last_px - r["entry"]) if side == "L" else (r["entry"] - self.last_px)
                if r_pts < 0.5:
                    return False                  # chỉ bồi lệnh 2 khi lệnh 1 đã có đệm lãi
        return True

    def _find_structural_wall(self, root_pos: dict) -> Optional[float]:
        """S4-HEDGE: tìm cản cấu trúc cho lệnh gốc (S → mức H PHÍA TRÊN entry · L → mức L PHÍA DƯỚI).
        Nguồn (live, không lookahead): lvl strong_zones (confirmed·alive) + levels strategy
        (confirmed·không-broken) + FZ grid (touches ≥ FZ_MIN_TOUCH, chưa broken).
        Chọn mức gần giá hiện tại nhất. None = không có cản (→ nhánh PRUNE_SPAN)."""
        c = self.cfg
        px, entry, side = self.last_px, root_pos["entry"], root_pos["side"]
        min_touch = getattr(c, "FZ_MIN_TOUCH", 2)
        cands: list = []
        try:
            if side == "S":
                cands += [z["px"] for z in _lvl.strong_zones("S", self.now_ts)]
                cands += [lv.px for lv in self.levels if lv.kind == "H" and lv.confirmed and not lv.broken]
                cands += [lvl for lvl, e in self.fz_tops.items() if e[0] >= min_touch and not e[2]]
                above = [w for w in cands if w > entry]
                return min(above, key=lambda w: abs(w - px)) if above else None
            cands += [z["px"] for z in _lvl.strong_zones("B", self.now_ts)]
            cands += [lv.px for lv in self.levels if lv.kind == "L" and lv.confirmed and not lv.broken]
            cands += [lvl for lvl, e in self.fz_bots.items() if e[0] >= min_touch and not e[2]]
            below = [w for w in cands if w < entry]
            return min(below, key=lambda w: abs(w - px)) if below else None
        except Exception:
            return None                            # engine lvl chưa ready → fail-open (đủ levels/fz)

    def _manage_hedge_basket(self, root_pos: dict, open_pos: list) -> List[dict]:
        """S4-HEDGE — máy trạng thái 4-trạng thái của rổ lệnh gốc+đối-ứng:
        NAKED → (pnl ≤ −HEDGE_LOCK_PTS) ENTER leg HEDGE (không TP broker; executor gỡ TP root)
        → HEDGE_LOCKED: PRUNE_BREAK (px vượt cản ±HEDGE_BREAK_PTS, D3 branch=LOCKED) ·
          PRUNE_SPAN (không cản, span ≥ HEDGE_MAX_SPAN_PTS) · HEDGE_TAKE (giá tại cản + leg lãi
          ≥ HEDGE_MIN_PROFIT_PTS + giật lùi ≥ HEDGE_BOUNCE_CONFIRM_PTS khỏi wall_peak + không IMPULSE)
        → UNWOUND: BASKET_TP (net ≥ BASKET_TP_USD) · PRUNE_BREAK (quay đầu vượt peak/cản, D3 branch=UNWOUND)
          · PSL breaker (net ≤ −(PSL_PTS×2+0.48) = −$6.48).
        hedge_credit = lãi ƯỚC TÍNH leg (pts×$2) — main sync giá trị THẬT từ broker khi EXIT ok.
        State (wall_px/wall_peak_px/unwound/credit) mirror vào self.hedge_baskets → snapshot (D.1)."""
        c = self.cfg
        p, px = root_pos, self.last_px
        root_id = p["id"]
        leg = next((q for q in open_pos if q.get("parent_id") == root_id and q.get("leg_type") == "HEDGE"), None)
        pnl_pts = (px - p["entry"]) if p["side"] == "L" else (p["entry"] - px)
        acts: List[dict] = []
        brk = getattr(c, "HEDGE_BREAK_PTS", 1.0)

        def _emit() -> None:
            """Mirror state rổ → registry persistence (lúc root chưa đóng; decide() prune khi root mất)."""
            self.hedge_baskets[root_id] = dict(
                wall_px=p.get("wall_px"),
                wall_peak_px=p.get("wall_peak_px"),
                leg_ids=[q["id"] for q in open_pos if q.get("parent_id") == root_id and q.get("leg_type") == "HEDGE"],
                unwound=p.get("unwound") is True,
                hedge_credit=float(p.get("hedge_credit", 0.0)),
            )

        # ── NAKED: chưa khóa, chưa gỡ khóa → mở chân đối ứng khi lỗ chạm ngưỡng ──
        if leg is None and p.get("unwound") is not True:
            if pnl_pts <= -getattr(c, "HEDGE_LOCK_PTS", 1.2):
                w = p.get("wall_px")
                if not w:
                    w = self._find_structural_wall(p)     # cản hiện tại (cũ/None → tìm lại, không lookahead)
                p["wall_px"] = w
                acts.append({
                    "kind": "ENTER_LONG" if p["side"] == "S" else "ENTER_SHORT",
                    "px": px, "anchor": w if w is not None else 0.0,
                    "level_ts": self.now_ts, "touch": 0, "drift5m": 0.0,
                    "parent_id": root_id, "leg_type": "HEDGE",
                })
            _emit()
            return acts

        # ── HEDGE_LOCKED: đang có chân đối ứng mở song song ──
        if leg is not None:
            leg_pts = (px - leg["entry"]) if leg["side"] == "L" else (leg["entry"] - px)
            wall = p.get("wall_px")
            # tìm lại cản khi khóa lúc không có cản (wall_px=0/None) — cho phép upgrade PRUNE_SPAN→BREAK
            if not wall:
                wall = self._find_structural_wall(p)
                p["wall_px"] = wall
            # Nhánh tỉa 1 (D3): phá cản ≥ HEDGE_BREAK_PTS → EXIT CẢ HAI (lỗ ròng đóng băng ≈ −$3.36)
            if wall:
                broke = (px >= wall + brk) if p["side"] == "S" else (px <= wall - brk)
                if broke:
                    for tgt in (p, leg):
                        acts.append({"kind": "EXIT", "pos_id": tgt["id"],
                                     "reason": "PRUNE_BREAK", "branch": "LOCKED", "px": px})
                    _emit()
                    return acts
            # Nhánh tỉa 2: không tìm thấy cản + span adverse ≥ HEDGE_MAX_SPAN_PTS → tỉa cặp
            if not wall and pnl_pts <= -getattr(c, "HEDGE_MAX_SPAN_PTS", 4.5):
                for tgt in (p, leg):
                    acts.append({"kind": "EXIT", "pos_id": tgt["id"], "reason": "PRUNE_SPAN", "px": px})
                _emit()
                return acts
            # Nhánh gỡ khóa: giá trong band cản + leg lãi ≥ MIN_PROFIT + giật lùi BOUNCE_CONFIRM
            # khỏi wall_peak (cực adverse: S=đỉnh · L=đáy) + M0 != IMPULSE → EXIT leg (HEDGE_TAKE)
            band = getattr(c, "FZ_BAND_PTS", 0.5)
            in_band = False
            if wall:
                in_band = (wall - band <= px <= wall + brk) if p["side"] == "S" else (wall - brk <= px <= wall + band)
            if wall and in_band:
                peak = p.get("wall_peak_px")
                p["wall_peak_px"] = (max(peak, px) if peak is not None else px) if p["side"] == "S" \
                                    else (min(peak, px) if peak is not None else px)
                p2 = p["wall_peak_px"]
                bounced = (p2 - px) >= getattr(c, "HEDGE_BOUNCE_CONFIRM_PTS", 0.4) if p["side"] == "S" \
                           else (px - p2) >= getattr(c, "HEDGE_BOUNCE_CONFIRM_PTS", 0.4)
                if bounced and leg_pts >= getattr(c, "HEDGE_MIN_PROFIT_PTS", 1.5) and self.m0_regime != "IMPULSE":
                    p["unwound"] = True
                    p["hedge_credit"] = leg_pts * 2.0      # ước tính $/pt@LOT=0.02 (main sync broker thật)
                    acts.append({"kind": "EXIT", "pos_id": leg["id"], "reason": "HEDGE_TAKE",
                                 "parent_id": root_id, "px": px})
                    _emit()
                    return acts
            _emit()
            return acts

        # ── UNWOUND: leg đã chốt (credit đã bank) → chốt rổ / tỉa / cầu chì ──
        oz = getattr(c, "LOT", 0.02) * 100.0              # $/pt (LOT 0.02 = 2oz = $2/pt)
        net = pnl_pts * oz + float(p.get("hedge_credit", 0.0))
        ref = p.get("wall_peak_px") or p.get("wall_px")
        if net >= getattr(c, "BASKET_TP_USD", 0.50):
            acts.append({"kind": "EXIT", "pos_id": root_id, "reason": "BASKET_TP", "px": px})
        elif ref and ((px >= ref + brk) if p["side"] == "S" else (px <= ref - brk)):
            acts.append({"kind": "EXIT", "pos_id": root_id, "reason": "PRUNE_BREAK",
                         "branch": "UNWOUND", "px": px})   # D3: mã thoát chung, log phân nhánh
        elif net <= -(getattr(c, "PSL_PTS", 3.0) * 2.0 + 0.48):
            acts.append({"kind": "EXIT", "pos_id": root_id, "reason": "PSL", "px": px})  # PSL breaker −$6.48
        _emit()
        return acts

    # ─────────────────────────── DECISION ───────────────────────────
    def decide(self, open_pos: List[dict], windows, rol_min: int) -> List[dict]:
        """open_pos: [dict(id, side 'L'/'S', entry, entry_ts, anchor)] → list actions"""
        c = self.cfg
        acts: List[dict] = []
        now = self.now_ts
        n_open = len(open_pos)
        # ENTRY — branch theo cfg.MODE (mặc định B_SNEO):
        #   MOM1 (CHAIRMAN 13-10 18:xx): net px vs K M1 close ≥ +THR = MUA · ≤ −THR = BÁN, 1 lệnh/nến
        #   B_SNEO (13-10 tối): TRIGGER B trên S-ladder (S-chạm + bounce ≥$S_BOUNCE_PTS)
        if self.last_px is not None and self.in_window(now, windows) and n_open < c.K_CONTEXT:
            if getattr(c, "MODE", "B_SNEO") == "MOM1":
                # ── MOM1: GIÁ LÊN MUA LÊN · GIÁ XUỐNG BÁN XUỐNG (momentum M1) ──
                cur_min = now // 60
                # RE-FIRE GATE (CHAIRMAN tối 2): 1 candle M1 = mom_fire_count lệnh (reset mỗi nến);
                # limit = pb_arm_pc (PULLBACK, mạnh +1) hoặc MOM_MAX_PER_CANDLE (EDGE). Mặc định 1 = chống spam.
                if self.mom_fire_min != cur_min:
                    self.mom_fire_min, self.mom_fire_count = cur_min, 0
                if getattr(c, "MOM_ENTRY", "EDGE") == "PULLBACK":
                    # TIMING Ở ĐỈNH/ĐÁY (CHAIRMAN 19:xx): tín hiệu tại close nến → armed dip/bật
                    # (đỉnh nến −pub cho MUA · đáy nến +pub cho BÁN) — KHÔNG đuổi đỉnh
                    s_side = self.pb_arm_side
                    arm_alive = (self.pb_arm_min >= 0
                                  and cur_min >= self.pb_arm_min
                                  and cur_min <= self.pb_arm_min + self.pb_arm_len - 1)
                    if (arm_alive and self.mom_fire_count < self.pb_arm_pc
                            and ((s_side == "L" and self.last_px <= self.pb_arm_px)
                                 or (s_side == "S" and self.last_px >= self.pb_arm_px))):
                        # S3-B G2-A: CHẶN CỨNG v0 entry (LVL+EXT15) — không burn re-fire slot
                        # (spec: "unmet → do not enter, arm stays alive — EDGE waits next tick, pc intact")
                        if self._g2_block("S" if s_side == "S" else "B"):
                            pass
                        elif not self._can_open_new_root(s_side, open_pos):
                            pass            # S4 ORCHESTRATOR: chặn lệnh gốc (chưa thỏa gap/step/root-cap) — arm giữ (không burn slot)
                        else:
                            self.mom_last_candle_min = cur_min
                            self.mom_fire_count += 1
                            mom = self.mom_net()
                            acts.append({
                                "kind": "ENTER_LONG" if s_side == "L" else "ENTER_SHORT",
                                "px": self.last_px, "anchor": 0.0,
                                "level_ts": now, "touch": c.MOM_K_BARS, "drift5m": round(mom, 3),
                            })
                else:
                    mom = self.mom_net()
                    pc_limit = getattr(c, "MOM_MAX_PER_CANDLE", 1)
                    if mom >= c.MOM_THR_PTS and self.mom_fire_count < pc_limit and self._can_open_new_root("L", open_pos):
                        if self._g2_block("B"):      # S3-B G2-A (v0 entry B bị chặn tại H-zone/EXT15)
                            pass
                        else:
                            self.mom_last_candle_min = cur_min
                            self.mom_fire_count += 1
                            acts.append({
                                "kind": "ENTER_LONG", "px": self.last_px, "anchor": 0.0,
                                "level_ts": now, "touch": c.MOM_K_BARS, "drift5m": round(mom, 3),
                            })
                    elif mom <= -c.MOM_THR_PTS and self.mom_fire_count < pc_limit and self._can_open_new_root("S", open_pos):
                        if self._g2_block("S"):      # S3-B G2-A (v0 entry S bị chặn tại L-zone/EXT15)
                            pass
                        else:
                            self.mom_last_candle_min = cur_min
                            self.mom_fire_count += 1
                            acts.append({
                                "kind": "ENTER_SHORT", "px": self.last_px, "anchor": 0.0,
                                "level_ts": now, "touch": c.MOM_K_BARS, "drift5m": round(mom, 3),
                            })
            else:
                # ── B_SNEO (bản 13-10 tối): trigger B trên S-ladder (giữ nguyên, fallback) ──
                acted = False
                for x in self.levels:
                    if (
                        x.kind == "L" and x.confirmed and not x.broken and not x.consumed
                        and 1 <= x.touches <= c.MAX_TOUCH and self.last_px >= x.px + c.S_BOUNCE_PTS
                    ):
                        if self._g2_block("B"):       # S3-B G2-A (fallback B_SNEO cũng gate)
                            break
                        if not self._can_open_new_root("L", open_pos):
                            break            # S4 ORCHESTRATOR: chặn lệnh gốc — không consumed, chờ cơ hội khác
                        x.consumed = True
                        acts.append({
                            "kind": "ENTER_LONG", "px": self.last_px, "anchor": x.px,
                            "level_ts": x.ts, "touch": x.touches, "drift5m": self.drift5m(),
                        })
                        acted = True
                        break
                if not acted:
                    for x in self.levels:
                        if (
                            x.kind == "H" and x.confirmed and not x.broken and not x.consumed
                            and 1 <= x.touches <= c.MAX_TOUCH and self.last_px <= x.px - c.S_BOUNCE_PTS
                        ):
                            if self._g2_block("S"):
                                break
                            if not self._can_open_new_root("S", open_pos):
                                break            # S4 ORCHESTRATOR: chặn lệnh gốc — không consumed, chờ cơ hội khác
                            x.consumed = True
                            acts.append({
                                "kind": "ENTER_SHORT", "px": self.last_px, "anchor": x.px,
                                "level_ts": x.ts, "touch": x.touches, "drift5m": self.drift5m(),
                            })
                            break
        # S3-B: R1/R2 STALL-FADE — FILL limit arm (tick proxy: giá chạm limit · cap K_CONTEXT
        # chung với v0 · không fill khi đã ROL · window check như v0). main đánh dấu r1r2=True
        # cho position mới (exit 4-lớp bên dưới) + tlog như thường (a.get anchor/touch).
        if (self.last_px is not None and self.now_ts
                and self.in_window(now, windows) and not self.in_rollover(now, rol_min)):
            for arm in list(self.r1r2_arms):
                if now >= arm["until"] or arm["key"] in self.r1r2_done:
                    self.r1r2_arms.remove(arm)
                    continue
                hit = (self.last_px <= arm["px"]) if arm["side"] == "S" else (self.last_px >= arm["px"])
                # S4: R1/R2 = lệnh ROOT → gate ORCHESTRATOR (baseline HEDGE_ENABLE=False
                # ≡ n_open < K_CONTEXT — regression giữ nguyên; True = MAX_ROOT/gap/step + chừa slot HEDGE)
                if hit and self._can_open_new_root("S" if arm["side"] == "S" else "L", open_pos):
                    self.r1r2_arms.remove(arm)
                    self.r1r2_done.add(arm["key"])   # row 18: 1 lệnh/zone/ngày/hướng (live strict)
                    acts.append({
                        "kind": "ENTER_SHORT" if arm["side"] == "S" else "ENTER_LONG",
                        "px": arm["px"], "anchor": arm["lvl_px"],
                        "level_ts": arm["ts"], "touch": arm.get("touches", 0), "drift5m": 0.0,
                        "arm": arm["key"][0], "regime": arm.get("regime", ""),
                    })
        # EXIT LADDER
        #   B_SNEO: TP | DRIFT-flip (P&L<0) | S_BREAK | TIME15 | ROL
        #   MOM1 (CHAIRMAN 19:xx "KHÔNG TỈA LỆNH KHI PNL ÂM → CHỜ GIÁ QUAY LẠI" + "LỆNH CHẠY CÙNG GIÁ"):
        #     NOW    : TP | TIME | ROL (F3)
        #     WAITPOS: TP/RAIL | TIME CHỈ KHI PnL≥0 | ROL — lệnh LỖ được GIỮ, chờ giá quay lại TP
        #     WAIT   : TP/RAIL | ROL (không TIME)
        #     RATCHET: lãi thuận ≥MOM_TRAIL_ACT → hủy TP 1.5 (để lệnh chạy) · ≥MOM_RATCHET_ACT → TRAIL đỉnh−MOM_TRAIL_LAG
        d = self.drift5m()
        rol = self.in_rollover(now, rol_min)
        mom1 = getattr(c, "MODE", "B_SNEO") == "MOM1"
        pol = getattr(c, "MOM_EXIT_POLICY", "NOW")
        tstop = getattr(c, "MOM_TIME_STOP", 15) if mom1 else c.TIME_STOP_MIN
        psl = getattr(c, "PSL_PTS", 0.0) or 0.0   # S1 14/10: risk-brake −3pts (≈−6.48$ có spread), VÔ ĐIỀU KIẾN mọi policy
        # S3-B: DRIFT-FLIP m1-proxy — update count adverse-liên-tiếp tại ranh m1 (R-positions)
        _df_min = now // 60
        if self._df_last_min != _df_min:
            self._df_last_min = _df_min
            self._df_update_counts(open_pos)
        for p in open_pos:
            # S4-HEDGE: chân HEDGE (parent_id ≠ ∅) — quản lý bởi _manage_hedge_basket của ROOT
            # (skip vòng EXIT đơn lệnh). Khi ROL kích hoạt → đóng TOÀN BỘ (ROOT + HEDGE, reason="ROL").
            if p.get("parent_id"):
                if rol:
                    acts.append({"kind": "EXIT", "pos_id": p["id"], "reason": "ROL", "px": self.last_px})
                continue
            pnl_pts = (self.last_px - p["entry"]) if p["side"] == "L" else (p["entry"] - self.last_px)
            is_r = p.get("r1r2")        # S3-B: R1/R2 → exit 4-lớp (TP/PSL/ROL/DRIFT-FLIP, KHÔNG TIME)
            reason = None
            # S4-HEDGE: rổ LOCKED (chân HEDGE mở song song) / UNWOUND (đã gỡ khóa, credit đã bank)
            # → BỎ QUA mọi EXIT đơn lệnh (TP/TIME/PSL/DRIFT/S_BREAK/FADE — miễn MOM_TIME_STOP 10' theo plan);
            # máy rổ _manage_hedge_basket phát PRUNE_BREAK/PRUNE_SPAN/HEDGE_TAKE/BASKET_TP/PSL-breaker.
            # ROL ưu tiên tuyệt đối: đóng root (legs xử lý ở nhánh parent_id trên) — KHÔNG prune khi ROL.
            hedge_on = getattr(c, "HEDGE_ENABLE", False)
            managed = (any(q.get("parent_id") == p["id"] and q.get("leg_type") == "HEDGE" for q in open_pos)
                       or p.get("unwound") is True)
            if rol and hedge_on:
                self.peak_fav.pop(p["id"], None)
                acts.append({"kind": "EXIT", "pos_id": p["id"], "reason": "ROL", "px": self.last_px})
                continue
            if hedge_on and managed:
                acts.extend(self._manage_hedge_basket(p, open_pos))
                self.peak_fav.pop(p["id"], None)
                continue
            if psl > 0 and pnl_pts <= -psl:
                reason = "PSL"     # ưu tiên đầu: thoát trước mọi TP/ratchet/DRIFT/FADE/TIME/ROL
            if reason is None and is_r:
                # S3-B R1/R2 4-lớp (spec §14 row 19): TP | DRIFT-FLIP (m1-proxy: 2 nến m1 drift
                # adverse liên tiếp khi PnL<0, close-based) | ROL — KHÔNG TIME (row 19 chốt 4 lớp)
                if pnl_pts >= c.TP_POINTS:
                    reason = "TP"
                if reason is None and self._df_count.get(p["id"], 0) >= int(getattr(c, "DRIFT_FLIP_TICKMIN", 2)):
                    reason = "DRIFT"
            if reason is None and mom1 and pol != "NOW" and not is_r:
                # ── RATCHET: theo dõi đỉnh lãi thuận mỗi lệnh (cho tp_plan() + exit TRAIL) ──
                px = self.last_px
                pf = self.peak_fav.get(p["id"])
                if pf is None:
                    self.peak_fav[p["id"]] = px
                elif p["side"] == "L" and px > pf:
                    self.peak_fav[p["id"]] = px
                elif p["side"] == "S" and px < pf:
                    self.peak_fav[p["id"]] = px
                pf = self.peak_fav[p["id"]]
                fav = (pf - p["entry"]) if p["side"] == "L" else (p["entry"] - pf)
                if fav >= c.MOM_RATCHET_ACT:
                    lvl = pf - c.MOM_TRAIL_LAG if p["side"] == "L" else pf + c.MOM_TRAIL_LAG
                    if (p["side"] == "L" and px <= lvl) or (p["side"] == "S" and px >= lvl):
                        reason = "TRAIL"   # lệnh đã "chạy cùng giá" → chốt đỉnh−0.5 (luôn ≥ +1.5pts)
                elif pnl_pts >= c.TP_POINTS and fav < c.MOM_TRAIL_ACT:
                    reason = "TP"          # TP gốc (vùng 1.2–2.0: TP đã hủy → chờ 2.0 để TRAIL hoặc giá quay lại)
                if reason is None and self._break_exit(p, pnl_pts):
                    reason = "S_BREAK"     # S1: lệnh LỖ phá S-confirmed nghịch → thoát (WAIT/WAITPOS; TIME bên dưới giữ nguyên)
                if reason is None and now - p["entry_ts"] >= tstop * 60:
                    if pol == "WAITPOS" and pnl_pts < 0:
                        pass                # "KHÔNG TỈA LỆNH KHI PNL ÂM" → giữ, chờ giá quay lại
                    elif pol != "WAIT":
                        reason = "TIME"     # NOW: vô điều kiện · WAITPOS: chỉ PnL≥0 · WAIT: không có TIME
            elif reason is None and not is_r:   # S3-B: R-position (r1r2) chỉ dùng 4 lớp TP/PSL/ROL/DRIFT-FLIP → không vào chain này
                if pnl_pts >= c.TP_POINTS:
                    reason = "TP"
                elif not mom1 and ((p["side"] == "L" and d <= 0 and pnl_pts < 0) or (
                    p["side"] == "S" and d >= 0 and pnl_pts < 0
                )):
                    reason = "DRIFT"
                elif not mom1 and p["side"] == "L" and self.lowest_conf_l is not None and self.lowest_conf_l < p["anchor"] - c.S_CHAIN_BREAK:
                    reason = "S_BREAK"
                elif not mom1 and p["side"] == "S" and self.highest_conf_h is not None and self.highest_conf_h > p["anchor"] + c.S_CHAIN_BREAK:
                    reason = "S_BREAK"
                elif mom1 and getattr(c, "MOM_FADE_EXIT", False) and (
                    (p["side"] == "L" and self.mom_net() <= -c.MOM_THR_PTS)
                    or (p["side"] == "S" and self.mom_net() >= c.MOM_THR_PTS)
                ):
                    reason = "FADE"
                elif mom1 and self._break_exit(p, pnl_pts):
                    reason = "S_BREAK"     # S1 (MOM1): lệnh LỖ phá S-confirmed nghịch → thoát (dòng S_CHAIN B_SNEO trên giữ nguyên)
                elif now - p["entry_ts"] >= tstop * 60 and (not mom1 or pnl_pts >= 0):
                    reason = "TIME"         # S1: MOM1 chỉ TIME khi PnL≥0 (chờ giá quay lại) · B_SNEO (mom1=False) giữ vô điều kiện
            if reason is None and rol:
                reason = "ROL"
            if reason:
                self.peak_fav.pop(p["id"], None)
                acts.append({"kind": "EXIT", "pos_id": p["id"], "reason": reason, "px": self.last_px})
            # S4-HEDGE NAKED (root chưa khóa, chưa unwind — managed đã continue ở trên):
            # máy rổ phát ENTER chân đối ứng khi pnl ≤ −HEDGE_LOCK_PTS (chỉ ENTER, không EXIT).
            # Tick đã quyết EXIT cho root (PSL/TIME/DRIFT/ROL/TP...) → KHÔNG mở hedge mới.
            if hedge_on and reason is None:
                acts.extend(self._manage_hedge_basket(p, open_pos))
        # dọn peak_fav vị thế đã chết (adopt/recover không reset dict)
        live_ids = {p["id"] for p in open_pos}
        for pid in list(self.peak_fav):
            if pid not in live_ids:
                del self.peak_fav[pid]
        # S4: prune mirror rổ (root đã đóng cuối tick → registry sạch trước save_state)
        if getattr(c, "HEDGE_ENABLE", False):
            live_roots = {q["id"] for q in open_pos if not q.get("parent_id")}
            for k in [k for k in self.hedge_baskets if k not in live_roots]:
                del self.hedge_baskets[k]
        return acts

    def tp_plan(self, open_pos: List[dict]) -> Dict[str, Optional[float]]:
        """MOM1 ratchet (CHAIRMAN 19:xx "lệnh chạy cùng giá"): kế hoạch TP broker per vị thế.
        fav ≥ MOM_RATCHET_ACT → NÂNG TP lên đỉnh_lãi ± MOM_TRAIL_LAG (kèm giá)
        MOM_TRAIL_ACT ≤ fav < RATCHET → HỦY TP (None) để lệnh được chạy tiếp
        MODE≠MOM1 hoặc pol=NOW → {} (TP 1.5 đặt lúc enter giữ nguyên)."""
        c = self.cfg
        if getattr(c, "MODE", "B_SNEO") != "MOM1" or getattr(c, "MOM_EXIT_POLICY", "NOW") == "NOW":
            return {}
        plan: Dict[str, Optional[float]] = {}
        for p in open_pos:
            pf = self.peak_fav.get(p["id"])
            if pf is None:
                continue
            sgn = 1 if p["side"] == "L" else -1
            fav = sgn * (pf - p["entry"])
            if fav >= c.MOM_RATCHET_ACT:
                plan[p["id"]] = round(pf - sgn * c.MOM_TRAIL_LAG, 2)
            elif fav >= c.MOM_TRAIL_ACT:
                plan[p["id"]] = None
        return plan
