"""XAU_SCALP5 — bộ tham số duy nhất (drift5m + swing M5 + no-SL).
Giá trị gốc: findings/XAU_TREND_CHASE_M1_SIM.md + findings/ENTRY_PIPELINE.md
(đo từ M1 n=15,000 kimlong DB, 28-09→13-10, CHAIRMAN duyệt 13-10)
"""
from typing import Final

# --- hằng kỹ thuật (copy từ XAU_new src/config/constants.py) ---
TICK_BUFFER_MAX: Final[int] = 1000
MILLISECONDS_PER_SECOND: Final[int] = 1000
TIMESTAMP_MS_THRESHOLD: Final[float] = 1e12

# --- CHIẾN LƯỢC (5 DÒNG QUY TẮC) ---
# DRIFT5m = ROLLING 5 NẾN M1 (QUYẾT ĐỊNH CỦA CHAIRMAN): drift = px_now − close_M1[-5]
# (giá 5 phút trước tính bằng M1 roll 5 nến, KHÔNG phải TF M5; M5 chỉ dùng cho S-ladder)
DRIFT5M_BUY: Final[float] = 2.5      # drift5m > +$2.5 = CHẾ ĐỘ MUA (P90 net-5' = $3.16)
DRIFT5M_SELL: Final[float] = -2.5    # drift5m < −$2.5 = CHẾ ĐỘ BÁN
TP_POINTS: Final[float] = 1.5        # TP = 1.5 pts = $3 @0.02lot (CHAIRMAN)
LOT: Final[float] = 0.02           # 0.02 lot = 2 oz = $2/point (CHAIRMAN CHỐT)
K_CONTEXT: Final[int] = 8        # lệnh ĐỒNG THỜI — P2-Tuned 15/10 (HUMAN): 4 lệnh gốc (MAX_ROOT_POSITIONS=4) + 4 slot chân HEDGE

# --- SWING M5 (S-ladder) ---
S_M5_SWINGS: Final[int] = 90         # 90 nến M5 = 7.5h buffer lấy swing trước (mở phiên)
S_CONFIRM_BOUNCE: Final[float] = 2.5 # S xác nhận = giá hồi ≥$2.5 khỏi S (≈69% range-M5 P50)
S_CONFIRM_MINS: Final[int] = 5       # HOẶC 5' không phá S mới
S_MERGE: Final[float] = 5.0         # tách mức <$5 = cùng 1 S
S_TOUCH_TOL: Final[float] = 0.5     # chạm = vào ±0.5$
S_TOUCH_SEP_MIN: Final[int] = 30    # 2 chạm cách nhau ≥30'
MAX_TOUCH: Final[int] = 2           # chỉ vào T1-T2 · T3+ = S KIỆT (CHẶN)
S_CHAIN_BREAK: Final[float] = 0.5   # S MỚI xác nhận DƯỚI S_low đang giữ (±$0.5) = BREAK
S_BOUNCE_PTS: Final[float] = 2.5    # TRIGGER B (S-neo, CHAIRMAN 13-10 tối):
                                     #   MUA = S_đáy chạm T1-T2 + giá BẬT LÊN ≥$2.5 từ đáy (drift từ dưới lên)
                                     #   BÁN = S_đỉnh chạm T1-T2 + giá TỤT ≥$2.5 từ đỉnh (drift từ trên xuống)
                                     #   → trigger = "xác nhận S giữ được", drift5m 5′ ròng chỉ còn cho EXIT-flip

# --- SWING M1 (S-ladder M1 — CHAIRMAN 13-10 tối: M5 "quá thô" cho TP 1.5pts) ---
# Cùng logic fractal ±2 nến + confirm/broken/touch/consumed, scale 1/5 (M5→M1):
# hằng giá $ và thời gian' chia 5. MAX_TOUCH giữ 2 (T3+ kiệt).
LADDER_TF: Final[str] = "M1"          # "M5" | "M1" — TF xây S-ladder (trước 13-10 tối = "M5")
S1_SWINGS: Final[int] = 600           # 600 nến M1 = 10h buffer ấm (≈ S_M5_SWINGS/9)
S1_CONFIRM_BOUNCE: Final[float] = 0.5 # S xác nhận = giá hồi ≥$0.5 khỏi S
S1_CONFIRM_MINS: Final[int] = 1       # HOẶC 1' trôi qua (M5: 5')
S1_MERGE: Final[float] = 1.0         # tách mức <$1 = cùng 1 S (M5: $5)
S1_TOUCH_TOL: Final[float] = 0.1     # chạm = vào ±0.1$ (M5: 0.5)
S1_TOUCH_SEP_MIN: Final[int] = 6     # 2 chạm cách nhau ≥6' (M5: 30')
S1_CHAIN_BREAK: Final[float] = 0.1   # S MỚI xác nhận DƯỚI/TRÊN anchor ±$0.1 = BREAK (M5: 0.5)

# --- EXIT LADDER (không SL) ---
TIME_STOP_MIN: Final[int] = 15      # 15' chưa TP → ra
# V2 RISK-BRAKE (spec rev 6.1 dòng #3 CHỐT · triển khai S1 14/10 — bằng chứng 14/10: 7 lệnh TIME-tail
# vượt −6$ (−12.01/−11.41/−9.93/−9.76/−9.14/−8.90/−6.91)):
PSL_PTS: Final[float] = 3.0        # PSL −6$ (3pts = 2×TP 1.5, VÔ ĐIỀU KIẾN, mọi policy) → chặn tail-lỗ
                                   # kèm S1: BREAK-EXIT (lệnh lỗ + S-confirmed nghịch bị phá) ·
                                   # MOM1: TIME chỉ còn cho lệnh PnL≥0 (loser → PSL/S_BREAK/ROL)
ROLLOVER_MIN: Final[int] = 21 * 60 + 45   # 21:45Z force-close
DAILY_LOSS_STOP: Final[float] = 30.0  # $30 lỗ trong ngày (≈54% equity $55) → dừng bot ngày
MAGIC: Final[int] = 20261013

# --- VẬN HÀNH (watchdog) ---
# 13-10 17:xx: websocket MetaApi chết im lặng 2 lần (16:48, 16:52 Hanoi) → tick đóng băng
# → main-loop (idle-gate theo now_ts) ngủ → bot ngồi im không có lệnh, không ai biết.
# tick STALE > TICK_STALE_SECONDS (Mon-Fri UTC) → StreamStalled → supervisor restart pipeline.
TICK_STALE_SECONDS: Final[int] = 300

# --- MODE CHIẾN LƯỢC (CHAIRMAN 13-10 18:xx) ---
# "MOM1": GIÁ LÊN MUA LÊN, GIÁ XUỐNG BÁN XUỐNG — vào-rapid, ra-rapid (TP + TIME ngắn), KHÔNG SL.
#          1 lệnh/M1 candle (chống re-fire) · spread 0.24pts/lượt đã tính trong replay.
# "B_SNEO": trigger B S-neo (bản 13-10 tối) — giữ làm fallback.
MODE: Final[str] = "MOM1"
MOM_K_BARS: Final[int] = 3        # hướng giá = net px_now − close cách K nến M1 (data: P(|net3|≥1.5)=38% nến)
MOM_THR_PTS: Final[float] = 1.5   # ngưỡng impulse (data: net3 P75=1.10 · P90=2.44 — 1.5 = ~P85)
MOM_TIME_STOP: Final[int] = 10    # phút — "RA LỆNH NHANH" (data PULLBACK 19-10: T10 = +$1123/11d tốt nhất;
                                  # T15 +$1052 · T5 yếu · EDGE: T15 −$321)
MOM_FADE_EXIT: Final[bool] = False  # True: LONG ra khi mom_net ≤ −THR · SHORT ra khi ≥ +THR (flip nhanh, chặn tail-loss TIME)

# --- MOM1 CHAIRMAn 19:xx: "2 lệnh đồng thời hơi ít" + "KHÔNG TỈA LỆNH KHI PNL ÂM → CHỜ GIÁ QUAY LẠI"
#   + "LỆNH CHẠY CÙNG GIÁ" (trailing ratchet) + TIMING LỆNH Ở ĐỈNH/ĐÁY (pullback)
MOM_EXIT_POLICY: Final[str] = "NOW"
#   "NOW"     (F3): TP | TIME vô điều kiện | ROL   → EDGE −$321 · PULLBACK +$1123/11d (9/11 ngày dương) ← SHIP
#   "WAITPOS": TP/ratchet | TIME CHỈ KHI PnL≥0 | ROL → "cấm tỉa lệnh lỗ, chờ giá quay lại" → PULLBACK +$157
#   "WAIT"   : TP/ratchet | ROL (không TIME) → PULLBACK −$813 (tail ROL −$60..−130)
#   KẾT LUẬN DATA: tỉa TIME-lỗ NHỎ (≤10′) TỐT HƠN "chờ giá quay lại" (ratchet + giữ lệnh lỗ = tail ROL khổng lồ)
MOM_TRAIL_ACT: Final[float] = 1.2   # lãi thuận ≥1.2pts → BỎ TP 1.5 (để lệnh chạy cùng giá, không chốt sớm) [WAIT/WAITPOS]
MOM_RATCHET_ACT: Final[float] = 2.0  # lãi thuận ≥2.0pts → TRAILING: TP = đỉnh_lãi − MOM_TRAIL_LAG (kèm giá lên) [WAIT/WAITPOS]
MOM_TRAIL_LAG: Final[float] = 0.5
MOM_ENTRY: Final[str] = "PULLBACK"  # "EDGE" (đuổi tick) | "PULLBACK" (TIMING ĐỈNH/ĐÁY:
MOM_PUB_PTS: Final[float] = 0.8     #   tín hiệu close nến M1 → vào lệnh ở DÍP: đỉnh nến −0.8 (MUA) / đáy nến +0.8 (BÁN)
                                     #   data: pub0.8 +$1052..1123 > pub0.5 +$797..889 > pub0.3 +$157..239
# RE-FIRE (CHAIRMAN 13-10 tối 2: "trend tốt thì refire được không?") — chống spam nhưng cho phép chồng lệnh theo trend
MOM_ARM_LEN: Final[int] = 1          # tín hiệu arm hiệu lực N nến M1 (mặc định 1 = arm 1 nến kế tiếp)
MOM_MAX_PER_CANDLE: Final[int] = 1   # tối đa N lệnh/candle M1 (1 = chống re-fire; >1 = cho phép re-fire)
MOM_STRONG_PTS: Final[float] = 2.5   # RE-FIRE SHIP (V3, data: +50 lệnh/ngày (+17%), PnL −3% vs V0=0) —
                                      # tín hiệu MẠNH (net3 ≥2.5) → arm +1 nến & re-fire +1 lệnh/candle; 0 = tắt (V0)
# FZ — FADE-ZONE (CHAIRMAN 13-10 tối 3: "vùng giá test ≥2 lần chưa break = hấp thụ quán tính
#  → nên lệnh NGƯỢC vì nó bật lại"): nến tín hiệu PULLBACK chạm H/L-zone (S-ladder, touches≥2,
#  chưa broken) → FADE = đảo lệnh ngược · SKIP = hủy lệnh tại vùng đó · OFF = như cũ
FZ_MODE: Final[str] = "FADE"         # "OFF" | "FADE" | "SKIP" — SHIP FADE (data 21:xx dataset cập nhật:
                                     #   V3+FADE +$1491/14d · 327/ngày vs V3+OFF +$1454 · SKIP bị re-fire mạnh triệt tiêu)
FZ_MIN_TOUCH: Final[int] = 2        # mức H/L phải được test ≥N nến M1
FZ_BAND_PTS: Final[float] = 0.5    # bán kính: đỉnh/đáy nến tín hiệu cách mức zone ≤0.5pts = chạm zone
FZ_GRID_PTS: Final[float] = 0.25   # lưới mức giá (đỉnh/đáy M1 làm tròn lên mức lưới gần nhất)
FZ_RECENT: Final[int] = 240        # chỉ nhớ mức test trong N nến M1 gần nhất (~4 giờ)
FZ_BREAK_PTS: Final[float] = 1.0  # close vượt mức ±1.0pts = level đã break (hết hiệu lực fade)
SPREAD_PTS: Final[float] = 0.24   # spread XAUUSDm Exness (đo log sync 13-10: 4186.83/4187.07) — PnL audit
WINDOWS_ALL: Final[bool] = True   # True = giao 00:00-21:45Z cả ngày (data 19:xx: ALLDAY +$2395/11d > EVENING +$1437
                                   #   > SESSION +$1123 · avg +0.289/đơn · slot 12Z ~27 lệnh/ngày · CHAIRMAn: "có lệnh ngay")

# --- CỬA GIỜ (UTC, phút) ---
WINDOWS: Final = ((7 * 60 + 30, 12 * 60), (13 * 60 + 30, 18 * 60 + 30))  # 07:30-12:00 · 13:30-18:30
SYMBOL: Final[str] = "XAUUSDm"

# --- LVL LADDER M1 (rev 7 §14 — S3-A: port _replay_lvl.py đã gate E6 · src/lvl.py) ---
LVL_TOUCH: Final[int] = 2          # touches ≥ 2 = STRONG
LVL_BAND: Final[float] = 0.5      # bán kính chạm zone (±0.5pts)
ZONE_PTS: Final[float] = 0.5      # gộp zone cùng kind: Δpx ≤ 0.5pts
ZONE_SPAN: Final[int] = 30        # ...và trong 30' (candle m1)
STALL_M1: Final[int] = 3          # STALL = 3 nến m1 không phá (R1/R2)
FADE_PTS: Final[float] = 2.5      # R1/R2: entry limit = mức zone ∓2.5pts
LVL_DEAD: Final[float] = 2.5      # DEAD: m1 CLOSE vượt zone ∓2.5pts (wick-exempt)
LIMIT_TTL: Final[int] = 15        # hạn mức limit-order R1/R2 (phút)
G2LVL_PTS: Final[float] = 2.0    # G2-LVL: px cách zone strong·alive ≤ 2.0pts → CHẶN

# --- M0 REGIME (spec rev 6 #11 — S3-B: ngưỡng snapshot + tag, hysteresis 120 tick-phút) ---
M0_SPEED_IMP: Final[float] = 0.5       # speed ngưỡng IMPULSE
M0_SPEED_RANGE: Final[float] = 0.25    # speed ngưỡng RANGE
M0_FORM: Final[float] = 0.5            # form-ratio ngưỡng
M0_EXT_AGE: Final[float] = 5           # extreme age tối đa (nến)
M0_HYST_TICKS: Final[int] = 120        # hysteresis đổi tag (tick-phút)
M0_GDIR_TOL_VREV: Final[float] = 0.5   # ngưỡng G-DIR tại V-REV
M0_REV_PTS_VREV: Final[float] = 0.75   # pts ngưỡng xác nhận REVERSE (V-REV)

# --- S4-HEDGE & UNIFIED CAMPAIGN ORCHESTRATOR (14/10 · P2-Tuned 15/10 HUMAN) ---
HEDGE_ENABLE: Final[bool] = True               # LIVE TOÀN DIỆN (15/10 HUMAN): P2-Tuned K=8 · MAX_ROOT=4 · STEP 0.35 · GAP 5s ·
                                                # per-position hedge · BASKET_TIME 30′ · UNWIND_BREAKEVEN. D2 OVERRIDE bởi HUMAN:
                                                # backtest m1-proxy không phản ánh tick thật → chấp nhận LIVE (rủi ro: tail NAKED/LOCKED
                                                # chưa có PSL breaker — worst_basket replay −$10.36; theo dõi live, sẵn O1 patch sau).
HEDGE_LOCK_PTS: Final[float] = 1.2             # Âm 1.2 pts (~-$2.40) -> mở lệnh đối ứng khóa lỗ (-$3.36 cả spread)
HEDGE_MIN_PROFIT_PTS: Final[float] = 1.5       # Chân Hedge phải lãi >= 1.5 pts tại cản mới xét gỡ khóa
HEDGE_BREAK_PTS: Final[float] = 1.0            # Giá vượt vùng cản >= 1.0 pt -> xác nhận PHÁ CẢN (PRUNE_BREAK)
HEDGE_BOUNCE_CONFIRM_PTS: Final[float] = 0.4   # Giá chạm cản và giật lùi >= 0.4 pt -> xác nhận cản giữ được (HEDGE_TAKE)
HEDGE_MAX_SPAN_PTS: Final[float] = 4.5         # Khoảng cách tối đa từ lệnh gốc nếu không tìm thấy cản (PRUNE_SPAN)
BASKET_TP_USD: Final[float] = 0.50             # Chốt lời toàn rổ khi (Floating PnL + Hedge Credit) >= +$0.50
BASKET_TP_TRIGGER_USD: Final[float] = 1.20     # P2-Tuned: UNWIND_BREAKEVEN_GUARD — peak rổ >= +1.20 rồi lùi về <= 0.50 → chốt (không để xanh quay đỏ)
HEDGE_TIMEOUT_MIN: Final[int] = 30            # P2-H: rổ LOCKED CÓ CẢN treo >= 30' mà net ròng <= -PSL_BASKET_USD → BASKET_TIME (giải phóng slot)
HEDGE_TIMEOUT_NOWALL_MIN: Final[int] = 15     # P2-H (Red Team O1-Pro): rổ KHÔNG tìm thấy cản (wall=None) — HEDGE_TAKE không thể
                                              # kích hoạt → timeout 15' (3 chu kỳ HB) thay 30' (chống chôn slot sideway hẹp)
BASKET_TIME_MAX_LOSS_USD: Final[float] = 6.48 # P2-H O1-Pro (HUMAN 15/10): sàn −1.50 = DEAD CODE (net frozen −2.1…−4.5
                                              # không bao giờ >= −1.50, 0/9 rổ 15/10) → −6.48: mọi net frozen đều qua floor,
                                              # rổ LOCKED đóng đúng lúc timeout (giải phóng slot, PnL frozen không đổi)
PSL_BASKET_USD: Final[float] = 6.48           # P2-H: cầu chì RỔ (net ≤ −6.48) đặt ĐẦU _manage_hedge_basket, mọi trạng thái
                                              # (NAKED/LOCKED; UNWOUND đã XÓA theo UNWOUND-PAIR 15/10) — chặn slippage khóa bất thường
HEDGE_WALL_PAD_PTS: Final[float] = 0.3        # P2-H (Red Team F1-Dir): đệm an toàn — cản phải nằm cách giá tham chiếu >= 0.3pts
                                              # về phía phòng thủ, không kích hoạt PRUNE_BREAK ngay giây khóa (bệnh 4s rổ #1)
HEDGE_RECOVERY_PTS: Final[float] = 1.0        # P2-H: giá QUAY ĐẦU thuận root ≥ 1.0pts (pnl_root ≥ +1.0) → PRUNE_RECOVERY
                                              # đóng cả cặp — xóa điểm mù kịch bản 2 (rổ #3/#4 01:08 kẹt 102′, B1/B3/B4 07:06-07:15)
REGISTRY_PRUNE_GRACE_SEC: Final[int] = 45     # P2-H M1: prune-guard — record registry chỉ xóa khi root vắng ≥ 45s (grace),
                                              # và KHÔNG BAO GIỜ wipe khi open_pos rỗng đột ngột (RPC stall)
# P2-H2 C7-spike (15/10 HUMAN-approved): PRE-LOCK RESCUE — lệnh NAKED DƯƠNG (đỉnh peak_fav ≥ +0.9pts,
# đã giật lùi ≥ 0.25pts) ghép 1 lệnh NAKED ÂM trong [-1.15, -0.45]pts (vùng TRƯỚC ngưỡng hedge −1.2)
# → đóng CẢ HAI khi net ≥ +$0.30 = chặn rổ hedge MỚI (prevention). Chỉ M0 ∈ {RANGE, CREEP}.
# Toán (HUMAN 15/10): 2 NAKED cùng chiều có ΔE_entry < TP_POINTS = 1.5pts → pnl_win ≥ +0.90 hiện tại
# KHÔNG BAO GIỜ cứu được loser cùng chiều vùng [-1.15, -0.60] → đổi ngưỡng trigger sang
# PEAK ≥ 0.9 (hiện tại ≥ +0.65) + band loser mở rộng [-1.15, -0.45] + net ≥ +0.15pts (+$0.30).
CROSS_RESCUE_ENABLE: Final[bool] = True
CROSS_RESCUE_PEAK_PTS: Final[float] = 0.9      # đỉnh lãi thuận winner (peak_fav − entry) ≥ +0.9pts
CROSS_RESCUE_PULLBACK_PTS: Final[float] = 0.25 # winner đã giật lùi ≥ 0.25pts từ đỉnh (đang chững)
CROSS_RESCUE_LOSS_MAX_PTS: Final[float] = 0.45 # loser NAKED âm tối đa −0.45pts (nặng hơn → không cứu, để hedge)
CROSS_RESCUE_LOSS_MIN_PTS: Final[float] = 1.15 # loser NAKED âm tối thiểu −1.15pts (trước ngưỡng khóa −1.2)
CROSS_RESCUE_MIN_NET_USD: Final[float] = 0.30  # net ròng cặp (pnl_win + pnl_lose) × $/pt ≥ +$0.30
HEDGE_ALLOW_SCALE_IN: Final[bool] = False      # Tắt nhồi lệnh mặc định để bảo toàn vốn tối đa
MIN_ROOT_STEP_PTS: Final[float] = 0.35         # P2-Tuned: chỉ chặn trùng giá sát < 0.35pt (các ROOT CÙNG CHIỀU), không chặn lệnh rải theo sóng
MIN_ROOT_GAP_SEC: Final[int] = 5               # P2-Tuned: giãn cách tối thiểu 5s giữa 2 ROOT cùng chiều (chống bắn trùng trong vài giây)
MAX_ROOT_POSITIONS: Final[int] = 4            # P2-Tuned: 4 lệnh gốc đồng thời (= công suất V2); chân HEDGE dùng slot riêng trong K_CONTEXT=8
# P2-Tuned: per-position hedge — root nào âm tự cặp chân HEDGE riêng (parent_id); KHÔNG khóa toàn cục;
# root UNWOUND (chân đã chốt) vẫn cho các root khác mở lệnh mới (slot gốc còn trống = tự do bắt sóng).
