# XAU SCALP5 — SPEC rev 6.1 "V2: EDGE · KHÔNG-TIME · 4 LỚP PHÒNG THỦ · M0 REGIME · MAP"

> Trạng thái: **DỰ THẢO PHẪU THUẬT — chưa code** (lệnh CHAIRMAN).
> rev 6: mọi tham số đã chốt · rev 6.1 (+M0/MAP): ✅ DUYỆT 14/10 (threshold M0 = giá trị khởi điểm, đo trên replay). · rev 6.1b (+NO-STOP ENTRY · CLOSE-FAIL FIX · EXIT_LOG integrity · diagram EN): ✅ DUYET (DUYỆT) 14/10.
> GHI CHÚ THUẬT NGỮ: nến 1 phút viết **m1** (thường) xuyên suốt spec; ký hiệu khối M0/MAP (HOA) = tên khối, không phải nến.
> Ngày: 14/10/2026 · Bằng chứng: DB scalp5.db (entry/exit/tick/m1) + log scalp5.out 14/10.

## 0. BẢNG QUYẾT ĐỊNH (đã chốt 100%)

| # | Quyết định | Trạng thái |
|---|---|---|
| 1 | Bỏ PULLBACK (arm dip/bật không xác nhận hướng) → **EDGE** (net3 ±1.5 tick-fire) | ✅ CHỐT |
| 2 | Bỏ TIME exit 10′ (đóng theo đồng hồ) | ✅ CHỐT |
| 3 | **PSL −6$ (3pts = 2×TP, vô điều kiện)** — phanh cứng bù cho mất TIME | ✅ CHỐT (an N/A2) |
| 4 | **DRIFT-FLIP: đo bằng tick/phút, KHÔNG wall-clock** — drift5m ngược dấu kéo ≥ 2 tick-phút (1 tick-phút = 60 tick; thin-market → cửa sổ kéo dài thực, thick → ngắn) | ✅ CHỐT |
| 5 | **FZ-FADE (|net3| < 2.5): VÀO LỆNH NGƯỢC CÙNG PX** (FADE thật, +1 lệnh bù) — không SKIP | ✅ CHỐT |
| 6 | G-DIR: 20 tick / 0.25pts + nến m1 gần ±0.25 | ✅ CHỐT |
| 7 | G2: CHẶN HẲN < 2.0pts cực 15′ + 2 nến liền kề tại cực | ✅ CHỐT |
| 8 | G-DRIFT: K=6, drift5m SIGNED (5 nến m1), ring 2 mẫu (mỗi 60 tick), chỉ entry cùng dấu | ✅ CHỐT |
| 9 | REVERSE −3$ (PnLWATCH): ≤1/vị thế, cooldown 180 tick | ✅ KHÓA THEO THIẾT KẾ |
| 10 | MAGIC · LOT 0.02 · TP 1.5pts · ROL 21:45Z | GIủ NGUYÊN (DAILY_LOSS_STOP → bổi, xem #14) |
| 11 | **M0 [REGIME]**: speed · form_ratio · extreme_age → tag IMPULSE/V-REVERSAL/RANGE/CREEP · hysteresis 2 tick-phút · lưu snapshot + DB regime_log | ✅ DUYỆT 14/10 (threshold khởi điểm, replay đo) |
| 12 | Gates regime-conditioned: FZ-FADE chỉ RANGE/CREEP · K6 chỉ IMPULSE · V-REVERSAL → G-DIR×2 + REVERSE ưu tiên | ✅ DUYỆT 14/10 |
| 13 | **MAP [PRICE-MAP]**: bảng dữ liệu trục thời gian–giá · hàng = các mức H-alive/L-alive liên tiếp (px · touches · regime_at · BOUNCE/BREAK · band V2) · boot rebuild từ DB + live-update + RENDER KPI | ✅ DUYỆT 14/10 |
| 14 | **NO-STOP ENTRY**: bo DAILY_LOSS_STOP $30 halt (evidence 09:54: halt tại day$=-41.34$, sai biến — chƿa dedup + FAIL thất bại) → thay bạng KPI alarm -30/-50/-75$ (biên day$ = dedup exit_log) | ✅ DUYỆT 14/10 |
| 15 | **CLOSE-FAIL FIX**: 'Position not found' → re-adopt broker · max 2 retry · drop + pending-sync (chởn vỒng lằp — evidence 09:55 x6) | ✅ DUYỆT 14/10 |
| 16 | **EXIT_LOG integrity**: UNIQUE(pos_id) · FAIL rows không ghi · sum PnL = dedup · PID-FILE khi khởi tạo | ✅ DUYỆT 14/10 |

## 1. LÝ DO (bằng chứng 14/10, chưa phải cảm tính)

| Lệnh | PnL | Cơ chế sai (chứng từ nến/tick DB) |
|---|---|---|
| 4868637394 S 01:38 | −8.90 | "Bán đáy": entry 4159.02 chỉ 1.4pts so đáy 4157.6 · nến 01:38 O=4158.5 C=4158.2 (giá vẫn trượt) |
| 4868653965 S 01:43 | −4.01 | FZ-FADE đảo impulse TĂNG (nến 01:42 C−O=+1.3, net3 +1.3→+2.3) thành BÁN — không có guard cường độ |
| 4868754645/4831 S 02:27 | −1.07/−1.54 | "Bán lúc giá vẫn tăng": 0.7–0.9pts dưới đỉnh, nến 02:25-29 tăng (4164→4166.1) |
| 4869145044 S 07:05 | **−12.01** (tail) | "Bán đáy" cách đáy 4154.7 = 2.34pts → G2@2.0 THỦNG → chỉ PSL/REVERSE bắt được |
| 4869273959 L 07:37 | −9.76 | Pipeline im 19′ (07:46→08:05) → TIME quá hạn bị kéo dài |
| 4868834871 L 03:02 | −3.14 | Bug side-flip (đã fix + deploy PID 92224 @06:39) |

| 4869939743/838 S 09:45 | −9.14/−9.93 | G2 + G-DIR (S vào khi up-drift: net3 > 0, nến cuối tâng — E5 replay xác minh) | — | PSL cap −6 | — | **không vào** (cƱu 6–9$ mội lệnh) |
| 4869876651 L 09:24 | +3.0 (TP broker, chƿa ghi) | — | — | — | — | exit-gap → fix #15/#16 (EXIT_LOG-SYNC + UNIQUE) |
09:54: day$=-41.34$ (biến chƿa dedup: 4869809349 ×10 row + double FAIL) → ENTRY HALT — chứng của NO-STOP (#14).
1 giổ 09:00→09:55 (dedup): wins +31.0$ · losses −49.99$ → net −16.19$. Toàn ngày 03:45→09:55 ≈ +11..15$ (exit_log dedup, chƿa tính broker-only).
Cắt lợi nhuận của TIME: 4868758050/8132 S 02:28 bị TIME đóng ở +0.55pts (+1.09/1.11$) thay vì giữ TP +3.00$ → bỏ TIME sửa luôn phần này.
Churn: 4868650156 TP +3.00 @01:42:42 → 18s sau vào S đáy (4868653965) → −4.01$.

## 2. PHÂN TÍCH FIRST-PRINCIPLES (7 khối nguyên tử, không chồng lấn)

1. **DATA**: nến m1/5m (DB) · tick (stream + deque-20) · ladder (fractal ±2) · drift5m (signed, 5 nến m1). Nguồn thật, không suy diễn.
2. **QUYẾT ĐỊNH HƯỚNG**: invariant SIGNED-ONLY (mục 5).
3. **ENTRY**: EDGE + FZ-FADE + gates G2/G3/G-DRIFT/G-DIR.
4. **EXIT**: TP · TRAIL (ratchet) · DRIFT-FLIP (tick-based) · PSL · ROL — không TIME.
5. **BACKSTOP LỖ**: PnL-WATCH REVERSE −3$ (khóa ≈ break-even).
6. **RESILIENCE + KPI**: boot exit_log-sync · gap · snapshot · adopt (simplified) · replay-gate trước ship.
7. **HÌNH THÁI (MORPHOLOGY)**: M0 regime (3 vô hướng + tag, hysteresis 2 tick-phút) + MAP price-map (hàng H/L-alive: touches · regime_at · BOUNCE/BREAK · band V2) — "trí nhớ hình thái" sống qua restart (mục 10).

## 3. ĐƠN VỊ DỮ LIỆU: TICK-PHÚT (thay wall-clock)

> CHAIRMANN: "DRIFT-FLIP không đo bằng thời gian mà đo bằng tick/phút."

- **1 tick-phút = 60 tick** (định nghĩa). Dài ngắn THỰC của 1 tick-phút tự hiệu chỉnh theo mật độ data:
  market thin (0.7 tick/s — đo: 207 tick/300s) → 60 tick ≈ 86s thực; market thick (1.2 tick/s — đo: 287 tick/240s) → ≈ 50s thực.
- Hệ quả: thin-market → cửa sổ persistence kéo dài hơn (ít data → confirm chậm hơn, chống persistence giả từ tick cũ);
  thick-market → confirm nhanh hơn (nhiều data → tin cậy nhanh). Đúng bản chất "đo bằng data, không đo bằng đồng hồ".
- Áp dụng:
  - **G-DRIFT ring**: mẫu dấu drift5m mỗi 60 tick → ring 2 mẫu = 120 tick.
  - **DRIFT-FLIP**: drift5m ngược dấu P kéo ≥ 2 tick-phút (120 tick) khi PnL < 0 → đóng P.
  - **REVERSE cooldown**: 180 tick (3 tick-phút).
  - **G-DIR**: cửa sổ 20 tick (giữ nguyên, vốn là tick-based ✓).
  - **M0 hysteresis**: đổi tag regime phải confirm qua 2 tick-phút (120 tick) — chống flutter tag theo cùng 1 đơn vị.

## 4. SƠ ĐỒ KHỐI TOÀN BỘ (rev 6, đã khóa tham số)

```
══════════ BOOT (almanac) ════════════════════
 [RPC sync] → [DEMO gate (hard)]
  → [EXIT_LOG-SYNC]  get_deals_by_time_range(ROL→now, magic=20261013)
       · group by position_id · missing exit row → INSERT (real pnl from deal, ts of deal)
       · idempotent: UNIQUE(pos_id) · FAIL close rows NEVER written (KPI log only)
  → [CANDLE-DB]  SELECT m1/5m since ROL (NO broker fetch)  → [GAP CHECK] missing → MetaApi fill
  → [SWINGS]  snapshot <4h → RESTORE (ladder+touches+ring+REVERSE-counter+regime+price-map)
              else REPLAY m1 (4 fake ticks per candle) → ladder + FZ grid + PRICE-MAP · verify L/H-alive
  → [ADOPT]  open positions: side via _pos_side ✓ · real entry_ts (openTime→time→brokerTime)
             · no 'TIME overdue' branch (TIME removed)
  → [CLOSE-FAIL FIX]  'Position not found' → re-query broker position list:
             gone → write row reason='SYNC_BROKER' (UNIQUE, idempotent) + drop state
             still there → retry close (MAX 2 consecutive) → drop + pending-sync (NO infinite loop)
  → LIVE

══════════ TICK LOOP - DATA (real ground truth) ══════════════
 tick → [LADDER] fractal ±2 (S1_*)
      → [m1 BUILD] candle close → m1_closed (60 candles) → HIGH_15 / LOW_15 (min/max of 15 candles)
      → [TICK-TAIL] deque 20 ticks (min/max)
      → [DRIFT5M]  px − close_m1[−5 candles] · SIGNED · rolling per tick
      → [TICK-CLOCK] count ticks: every 60 ticks → 1 drift5m sign sample → [RING 2 samples]
      → [FZ GRID]  0.25pts · test ≥2 · break 1.0
      → [REGIME]   m1-close: speed · form_ratio · extreme_age → tag (hysteresis 120 ticks)
      → [PRICE-MAP] update H/L-alive rows: px · touches · regime_at · BOUNCE/BREAK · G2/FZ bands

┌────────────────── ENTRY (EDGE - 'net3 signal light') ────────────────────────────────────────┐
│ mom_net() ≥ +1.5 → BUY · ≤ −1.5 → SELL (tick-fire)                                              │
│ pc/candle: 1 (strong |net3|≥2.5 → +1 - abs whitelist symmetric)                                 │
│ → [FZ] px touches zone tested ≥2, unbroken:                                                     │
│      |net3| < 2.5 & regime∈{RANGE,CREEP} → FADE: enter OPPOSITE at same px (tag FZ_FADE)        │
│      |net3| < 2.5 & regime∈{IMPULSE,V-REV} → NO-FADE (guard: do not fade a trend)               │
│      |net3| ≥ 2.5 → NO-FADE (strong-impulse guard 2.5, all regimes)                             │
│ → G2 (HARD-BLOCK): px within 2.0pts of HIGH_15/LOW_15 AND the 2 adjacent m1                     │
│      candles at the extreme run AGAINST the entry direction → SKIP                              │
│ → G3 TAG: passed G2 but still within 2.0pts of extreme → log/Telegram                           │
│      "TOP-BUY"/"BOTTOM-SELL" (KPI marker)                                                       │
│ → G-DRIFT: RING(2 samples x 60 ticks) PERSIST & drift5m ≥ +2.5 (≤ -2.5)                         │
│      & net3 same sign & regime=IMPULSE → K_eff = 6, new entries SAME-DIRECTION ONLY             │
│      (conditions lost → instant K=4, both directions)                                           │
│ → G-DIR (20 ticks / 0.25):                                                                      │
│      BUY:  px - min(20 ticks) ≥ 0.25  AND last m1 close C ≥ O - 0.25                            │
│      SELL: max(20 ticks) - px ≥ 0.25  AND last m1 close C ≤ O + 0.25                            │
│      (unmet → do not enter, arm stays alive - EDGE waits next tick, pc intact)                  │
│ [M0] V-REVERSAL: G-DIR tol x2 (0.25→0.5) · REVERSE PRIORITY (REV_PTS 0.75)                      │
│ → [EXEC] 0.02 · TP +1.5 broker-side · MAGIC · tag (FZ_FADE/G3/REVERSE_of)                       │
│ → [entry_log] INSERT (kind, px, tp, drift5m, net3, tags)                                        │
│┘───────────────────────────────────────────────────────────────────────────────────────────────━

 [EXIT] - NO TIME -
   TP +1.5 · TRAIL (profit ≥1.2 drop TP · ≥2.0 trail = peak_profit - 0.5)
   · DRIFT-FLIP: PnL<0 & drift5m opposite to P persists ≥ 2 tick-mins (120 ticks) → close P
   · PSL: P_pnl ≤ −6.0$ (3pts) → close P UNCONDITIONAL (hard brake)
   · ROL 21:45Z
   · DAILY: NO-STOP ENTRY (halt REMOVED, #14) - KPI alarms only:
     day$ (dedup basis) ≤ -30 → Telegram WARN · ≤ -50 CRIT · ≤ -75 FUSE (halve K_eff, never stop)
 [PERSIST] snapshot 5' + shutdown (ladder · touches · ring · REVERSE-counter · regime · price-map)
 [INvariants] every direction decision = SIGNED · abs whitelist 5 items ·
   replay-check: every entry sign(net3)=side (except tag FZ_FADE) - FAIL = block ship
   · EXIT_LOG: 1 row per pos_id (UNIQUE) · FAIL never written · dedup on aggregation
   · PID-FILE written at start (observed MISSING 14/10 09:59 -> monitoring blind)
```

## 5. INVARIANT HƯỚNG + ABS WHITELIST (audit 14/10, 10 vị trí)

**Quy tắc**: path quyết định HƯỚNG (entry side, exit side, pnl_pts, REVERSE side, FZ-inversion)
CHỈ dùng so sánh SIGNED. `abs()` chỉ được trong 5 mục whitelist sau:

| Whitelist | Vị trí | Lý do |
|---|---|---|
| FZ-band | strategy L190 `abs(lvl−zpx) ≤ 0.5` | distance — vô hướng theo định nghĩa |
| S-merge | strategy L286 `abs(px−last.px) < 1.0` | distance |
| TP-slippage | executor L148 `abs(tp2−tp) > 0.1` | distance |
| strong-boost | EDGE: `\|net3\| ≥ 2.5 → pc+1` (và FZ-guard 2.5) | cường độ đối xứng có chủ đích (mạnh cả 2 chiều đều đặc biệt) |
| test/replay | test_offline L101/103, _test_state L66 | kiểm thử |

`models.py L46 body()` = dead utility (0 caller) — không chạm. Không thêm abs nào mới vào path hướng.

## 6. MA TRẬN CHỨNG TỪ rev 6 vs LỆNG LỖ HÔM NAY (counterfactual)

| Lệnh | PnL thực | G2 | G-DIR | FZ-guard | PSL −6 | REVERSE −3 | Counterfactual rev 6 |
|---|---|---|---|---|---|---|---|
| 4868637394 S 01:38 | −8.90 | ✓ chặn (1.4pts, nến giảm) | ✓ (nến 01:38 giảm) | — | — | — | **không vào** (tiết kiệm 8.90) |
| 4868653965 S 01:43 | −4.01 | ✗ (3.0pts) | ✓ chặn (nến +1.3) | 2.3 < 2.5 → vẫn fade (G-DIR là lớp chặn thật) | — | — | **không vào** (tiết kiệm 4.01) |
| 4868754645/4831 02:27 | −1.07/−1.54 | ✓ chặn (0.7–0.9, nến tăng) | ✓ | — | — | — | **không vào** (tiết kiệm 2.61) |
| 4869145044 S 07:05 | **−12.01** | ✗ (2.34) | ✗ (đã hắt 0.5 + nến crash giảm = hợp lệ S) | — | ✓ cap −6.0 | ✓ (peak 4162.8 ≥ TP-REVERSE) → ≈ −0.3 | **khóa ≈ 0** (cứu 11.7) |
| 4869273959 L 07:37 | −9.76 | — | — | — | ✓ cap −6.0 (px 4156.6) | ✓ (TP-REVERSE 4156.5 đã khớp 07:42:50) → ≈ 0 | **cứu ≈ 9.5** |
| 4868834871 L 03:02 | −3.14 | — | — | — | — | — | bug side (đã fix, deploy 06:39) |

Tương tự cho lệnh THẮN bị TIME cắt (4868758050/8132: +0.55 → giữ tới TP +3.00, ×2 = +3.8$).
Tổng counterfactual ngày 14/10 ≈ **+26.79$ (exit_log thực) + ~14 (chặn) + ~21 (REVERSE/PSL) + 3.8 (TIME-cuts)** — replay 12 ngày để con số cuối (mục 8).

## 7. BOOT & PERSIST (chi tiết)
- **EXIT_LOG-SYNC**: `get_deals_by_time_range` (RPC ✓ probe 07:xx) → filter magic → nhóm position →
  INSERT row thiếu (`reason='TP_BROKER'/'CLOSED_BROKER'`, pnl từ deal, ts = ts deal). Chạy MỖI boot (boot = điểm đồng bộ tự nhiên).
- **NẾN-DB**: thay WARMUP-seed từ broker REST → seed từ DB sau GAP fill; fallback broker REST chỉ khi DB thiếu >10% phút dự kiến.
- **ADOPT**: giữ `_pos_side` + entry_ts thật (đã ship 06:39). Bỏ nhánh TIME-overdue.
- **Snapshot**: +2 keys (ring buffer dấu, REVERSE counter) — snapshot cũ thiếu keys = default an toàn (load_state tolerates).
- **CLOSE-FAIL FIX** (evidence 09:55 loop x6): 'Position not found' → re-query broker position list: (a) position biến mất (broker đã đóng) → ghi row reason='SYNC_BROKER' (pnl từ deal, UNIQUE pos_id idempotent) + drop khoân trạng thại; (b) position vịn còn (giỉn đoân) → retry close, TỐI ĐA 2 lạn liến tiếp; (c) vẫn thất bại → drop + pending-sync (boot EXIT_LOG-SYNC kặt lại) — không vào vỒng lằp. RECOVER 'enter missed tracking': lấy entry_ts/px Tị BROKER (openTime/price), không tạo lại.
- **EXIT_LOG integrity**: UNIQUE(pos_id) · row FAIL không bao giờ vào exit_log (chỉ KPI log) · mệi sum PnL (day$, KPI, replay) = dedup theo pos_id (row OK).
- **PID-FILE**: ghi PID khi khởi tạo, xóa sạch khi thỐi (quan sát 14/10 09:59: pid file mất → PID 2379 not tracked).

## 8. SANITY CHECK + BASELINE (cửa ship, Luật 9 — chưa chạy, chờ code)
- **E1**: replay tick/m1 14/10 qua G2+G-DIR+FZ-guard → 4 lệnh sai hướng phải bị chặn ≥4/4 (mục 6).
- **E2**: 9 lệnh TIME-loss 14/10 → PSL cap mọi lệnh ≤ −$6 (không lệnh nào vượt).
- **E3**: REVERSE 4869145044/4869273959 → net ≈ 0 (±1$) từ tick.
 - **E4**: M0 tag × 5 đoạn 14/10 (01:40-47 V-LÊN · 05:00-06:00 RANGE · 07:00-15 CRASH/V · 08:10-15 IMPULSE-XUỐNG · 08:44-45 V-ĐÁY) → 5/5 tag đúng; PRICE-MAP RENDER khớp m1 DB (mục 11).
 - **E5**: NO-STOP basis: day$ 14/10 không-dedup vs dedup (halt bị tất tại -41.34$ trong khi day$ dedup ≈ +11..15$) → ngƱồng alarm chạy trên biên dedup · CLOSE-FAIL regression: không có vị thằ nào >2 lạn retry close liến tiếp · EXIT_LOG UNIQUE: 0 row dup sau sync.
- **BASELINE GATE**: replay 12 ngày (test_offline, spread 0.24pts/lượt) v0 (hiện hành) vs v2 (rev 6):
  ship ⇔ **$/ngày ≥ v0** VÀ **tail ≤ −6.0** VÀ **invariant-check = 0 FAIL**. Đo thêm: n_lệnh, WR, max-open, churn (FZ-FADE entries). (rev 6.1) + **PnL theo regime × combo on/off gates theo regime** (chỉ ship combo ≥ baseline) + **số lệnh THẮN bị G2 chặn** (case 08:45 L@4145.22 +3.00) + FZ-FADE churn theo regime.

## 9. DIFF ƯỚC TÍNH (block-level, <~150 dòng)
- −45: block PULLBACK L177-211 + 6 trường pb_* (init/save/load) + nhánh adopt TIME-overdue.
- +80: gates G2/G3/G-DRIFT/G-DIR trong ENTRY-EDGE + FZ-guard 2.5 + FADE-same-px (tag FZ_FADE).
- +10: TICK-CLOCK (đếm 60 tick/mẫu) + ring 2 + HIGH_15/LOW_15 (2 dòng) + deque-20.
- +20: exit PSL + DRIFT-FLIP (tick-based 120 tick).
- +40: PnL-WATCH REVERSE (strategy) + open-with-tag (executor) + ≤1/pos + cooldown 180 tick.
- +35: EXIT_LOG-SYNC (main, boot).
- +25: NẾN-DB seed (main/WARMUP) + fallback.
 - +70: M0 (tính 3 scalars + hysteresis ~20 · gates regime ~25 · persist ~10) + MAP (update rows ~15 · RENDER biểu đồ 30p ~20 · regime_log/price_map_log ~5).
- config: +14 hằng số (PSL_PTS=3.0 · DRIFT_FLIP_TICKMIN=2 · GDIR_TICKS=20 · GDIR_PTS=0.25 · GDIR_CANDLE_TOL=0.25 · G2_PTS=2.0 · G2_CANDLE_N=2 · GDRIFT_PTS=2.5 · K_STRONG=6 · RING_SAMPLE_TICKS=60 · RING_SAMPLES=2 · FZ_STRONG_GUARD=2.5 · REV_PTS=1.5 · REV_COOLDOWN_TICKS=180) · −3 (MOM_TIME_STOP, MOM_PUB_PTS, MOM_ARM_LEN). · +7 M0 (M0_SPEED_IMP=0.5 · M0_SPEED_RANGE=0.25 · M0_FORM=0.5 · M0_EXT_AGE=5 · M0_HYST_TICKS=120 · M0_GDIR_TOL_VREV=0.5 · M0_REV_PTS_VREV=0.75)
- +20: CLOSE-FAIL fix (re-adopt + max-2-retry + pending-sync) trong executor.
- +10: NO-STOP (DAILY_LOSS_STOP → None + 3 KPI alarm -30/-50/-75$ biên dedup + FUSE tuân chỉ nội K_eff).
- +10: EXIT_LOG UNIQUE(pos_id) migration + write-on-OK-only + PID-FILE khi khởi tạo.

## 10. M0 [REGIME] — HÌNH THÁI GIÁ (rev 6.1 · DUYỆT 14/10 · chưa code)
> "lưu lại hình thái giá chạy để bot biết giá đi như thế nào để phản ứng" — trả lời: CÓ, bằng 3 vô hướng + 1 tag,
> tính từ data ĐANG CÓ (nến m1 + tick) — 0 nguồn data mới, 0 ML (Luật 1). Threshold dưới = KHỞI ĐIỂM (DUYỆT) để replay đo, không phải chân lý.
### 10.1 — 3 scalars (mỗi nến m1-close, sống từ m1_closed 60 nến + TICK-TAIL)
```
 speed       = |drift5m| / 5                 (pts/phút · abs = whitelist cường độ)
 form_ratio  = Σ|close−open| / Σ(high−low)  (5 nến)   (1.0 = nến thân đầy = trend · 0 = chop)
 extreme_age = phút (tick-phút) từ HIGH_15/LOW_15 gần nhất   ("cực TƯƠI" <5 · "cực CŨ")
```
### 10.2 — 4 tag (hysteresis 2 tick-phút = 120 tick khi CHUYỂN tag — đơn vị tick §3)
```
 IMPULSE    : speed ≥ 0.5 & form_ratio ≥ 0.5
 V-REVERSAL : extreme_age < 5 & speed ≥ 0.5 & sign(drift5m) VỪA LẬT
 RANGE      : speed < 0.25 & FZ touches ≥ 2
 CREEP      : thừa (mặc định)
```
threshold KHỞI ĐIỂM (DUYỆT 14/10): speed 0.5/0.25 · form 0.5 · extreme_age 5 · hysteresis 120 tick.
### 10.3 — REGIME → GATES (cùng signal, reaction đúng theo chế độ giá)
```
 regime      FZ-FADE            G-DRIFT K6      G-DIR                 REVERSE
 IMPULSE     TẮT (không fade trend)  BẬT          thường (mm tự xác nhận)  thường (1.5pts)
 V-REVERSAL  TẮT                 TẮT          NGHIÊT: tol 0.25→0.5   SỚM: REV_PTS 0.75
 RANGE       BẬT (tool fade của range)  —      thường               thường
 CREEP       Bật (mặc định)     —            thường               thường
```
Bằng chứng 14/10: 08:10 IMPULSE-XUỐNG = 6 short thắng (+19.9$) · 01:40-47 V-REVERSAL-LÊN = fade short chết (−4.01) ·
08:45 V-ĐÁY = LONG +3.00 (vừa là win, vừa là "vùng nguy hiểm mua-đầu-V") → replay phải đo BOTH chiều (E4 + baseline gate).
### 10.4 — LƯU (mảnh "biết giá đi như thế nào" qua restart)
- snapshot: +regime tag + vector → sửa đúng cái "mất trí nhớ hình thái" 19′ (07:46→08:05).
- DB bảng `regime_log`(ts, tag, speed, form, age, n_open, pnl_day) → KPI research + replay theo regime.
### 10.5 — CỬA KPI M0 (Luật 9): replay 12 ngày tag-regime → PnL theo regime × combo on/off gates →
chỉ ship combo ≥ baseline. Threshold 10.2 = số khởi điểm; replay quyết.
## 11. MAP [PRICE-MAP] — BẢNG DỮ LIỆU GIÁ NGÀY (rev 6.1 · DUYỆT 14/10 · chưa code)
> "bảng dữ liệu kiểu biểu đồ thời gian–giá để bot biết TOÀN DIỆN giá đã đi được trong ngày,
> các ngưỡng vừa thiết lập, hình thái di chuyển tại các H-alive / L-alive LIÊN TIẾP."
### 11.1 — CẤU TRÚC BẢNG (in-memory; 1 row = 1 mức H-alive / L-alive của ladder, LIỀN KỀ nhau theo px)
```
 kind (H/L) · px (fractal ±2) · t_created · touches · t_last_touch
 · regime_at (tag M0 tại lần chạm cuối — liên kết HINH THAI ↔ MỨC)
 · outcome: BOUNCE (phản xạ, chưa break 1.0) / BREAK (vượt → mức chết, sinh mức mới) / PENDING
 · band G2: [px∓2.0] (band chặn hẳn tại mức) · band FZ: [px±0.5] · drift_sign tại mức
```
### 11.2 — VÍ DỤ (hình thái 14/10, lấy từ m1 DB)
```
 L 4144.2 (08:3x) touches=2 regime_at=IMPULSE-X outcome=BREAK↑  [long-chặn-zone 4144.2–4146.2]
 L 4154.1 (07:3x) touches=3 regime_at=V-REV     outcome=BREAK↑  [short-hợp-lệ ≥ 4156.1]
 H 4163.0 (05:3x) touches=4 regime_at=RANGE     outcome=BREAK↓  [long-hợp-lệ < 4161.0]
 H 4166.1 (08:3x) touches=1 regime_at=IMPULSE-X outcome=PENDING   [long-chặn-zone 4164.1–4166.1]
```
### 11.3 — BOOT · LIVE · RENDER
- BOOT: REBUILD từ DB m1/5m (SWINGS replay → ladder → MAP rows) — 0 nguồn data mới.
- LIVE: update mỗi lần chạm/break mức (few dòng trong tick loop).
- RENDER (biểu đồ trục NGANG = thời gian / trục ĐỨNG = giá — đúng mẫu CHAIRMAN §① 01:35→02:30):
  log + Telegram tại boot · mỗi 30p · khi close → artifact "HÌNH THÁI GIÁ NGÀY".
- LƯU: snapshot (+price_map) + DB bảng `price_map_log` (KPI).
### 11.4 — KPI (regime_at × outcome): "mức IMPULSE thường BREAK · mức RANGE thường BOUNCE"
→ xác nhận trên replay rồi tune gates theo regime (cùng cửa KPI §10, không thêm cửa riêng).
## 12. THỨ TỰ TRIỂN KHAI (khi duyệt code)
1. Config + invariant-grep (0 abs mới trên path hướng).
2. Boot: NẾN-DB seed → EXIT_LOG-SYNC (kèm py_compile + test offline state round-trip).
3. Gates G2/G3/G-DIR/FZ-guard + EDGE (bỏ PULLBACK) — E1 chạy xanh.
4. PSL + DRIFT-FLIP (tick-based) + REVERSE — E2/E3 xanh.
6. CLOSE-FAIL + NO-STOP + EXIT_LOG UNIQUE + PID-FILE (E5 xanh).
7. Replay 12 ngày → BASELINE GATE (kếm regime + win-blocked) → ship (0 vị thằ mấ, kill old PID, verify boot-log + PID-FILE, probe balance).
7. Replay 12 ngày → BASELINE GATE (kếm regime + win-blocked) → ship (0 vị thằ mấ, kill PID cư, verify boot-log + PID-FILE, probe balance).



## 14. REV 7 — KHUNG LVL M1-ROLLING + R1/R2 STALL-FADE + THAM CHIẾU m15/1h/4h (bằng chứng DB 14/10 12:00–13:00)

> CHAIRMAN: "scalp thì swing M1 (rolling 5 nến) làm khung chính vì M5 bị trễ; m15/1h/4h chỉ tham chiếu."
> Đo 14/10 (DB m1/m5, đọc chỉ): M5 fractal ±2 confirm trễ ~15–25′ (4166.21: M5 02:45 vs M1 02:35 · 4157.5: M5 03:35 vs M1 01:40/03:24).
> M1 ±2 raw = noisy (pivot BOUNCE 28% vs M5 59% trong 60′) → bắt buộc filter STRONG.

| # | Quyết định | Trạng thái |
|---|---|---|
| 17 | **LVL chính = LADDER M1 (rolling 5×m1 = fractal ±2 nến M1, confirm ≈ 2′)** — trùng `LADDER_TF="M1"` + S1_* đã có trong config 13/10 tối · M5 BỎ làm khung chính (giữ chỉ làm cross-check offline) | ✅ CHỐT 14/10 |
| 18 | **STRONG level = touches ≥ 2** (±0.5pts, cách nhau ≥ 6′ — đúng FZ_MIN_TOUCH/FZ_BAND/S1_TOUCH_SEP) · **ZONE = gộp pivot cùng kind ≤ 0.5pts/30′ (px = max H / min L, 1 lệnh/zone/ngày/hướng)** · R1/R2 + G2-LVL chỉ chạy tại strong zone · **DEAD = close ∓ 2.5pts** (coherent với FADE_PTS — wick 1.0pt KHÔNG giết mức; FZ_BREAK 1.0 chỉ còn tag chart) | ✅ CHỐT (KPI: raw M1 pivot giữ nguyên → fade 72% false-BREAK) |
| 19 | **R1 STALL-TOP**: H strong + STALL (3 nến m1 kế tiếp không phá P+0.25 + net C−O 5 nến < 0, ≥ 3′ sau t_conf) → S-LIMIT @ P−2.5 (hạn mức 15′, fill khi low ≤ P−2.5) · exit giữ 4 lớp V2 (TP 1.5 · PSL −6$ · ROL · DRIFT-FLIP) | ✅ CHỐT (đo replay m1 10/14: 02:45 S @4163.80 từ zone H 4166.30 → TP 02:46 +2.52$ (chưa trừ spread: +3.00$)) |
| 20 | **R2 STALL-BOTTOM**: L strong + STALL mirror (net5 > 0) → B-LIMIT @ P+2.5 · mirror exit | ✅ CHỐT (đo replay m1 10/14: 03:53 B @4160.03 từ zone L 4157.53 → TP 03:57 +2.52$) |
| 21 | **G2-LVL** (nâng cấp G2 rev 6): entry S trong 2.0pts DƯỚI H-strong·alive (touches ≥ 2, chưa dead) → SKIP (NHÁNH LVL: bằng chứng cứng, KHÔNG cần điều kiện nến) · mirror B · NHÁNH EXT15 (extreme 15′, bằng chứng nhẹ) giữ điều kiện 2 nến m1 C≥O/C≤O | ✅ CHỐT (E6 §14.3: G2-A chặn 63 lệnh v0 — cf +22.26$ vs B +21.18$ → giữ A · giá trị = chặn tail 07:05 −12.01 · 02:27 ×2 −2.61 · 01:43 −4.01, phí small-win ≈ trung lập) |
| 22 | **THAM CHIẾU m15/1h/4h/D1 = VẠCH + TAG KPI, KHÔNG GATE entry** (lệnh CHAIRMAN) · ⚠️ DATA STALE: 1h kết thúc 10/12 · 4h 10/03 · D1 10/05 → **BACKFILL multi-TF (gap_filler) là tiên quyết** trước khi KPI theo khung reference có ý nghĩa | ✅ CHỐT + BACKLOG |
| 23 | **THỰC THI: V2 THAY THẾ v0 — 1 tiến trình duy nhất, KILL PID v0 khi ship (KHÔNG chạy song song)** · v0 đã chứng lỗi §1 (8 lệnh sai hướng: bán đáy 01:38/07:05 · fade đảo impulse 01:43/09:45 · TIME kéo tail −11..−12$) | ✅ CHỐT |
| 24 | **S1 RISK-BRAKE (14/10, gate replay V1):** PSL `PSL_PTS=3.0` (−6.48$ có spread) check ĐẦU TIÊN, vô điều kiện mọi policy · BREAK-EXIT `_break_exit()` (MOM1: S-confirmed nghịch bị phá → S_BREAK — L: px<lowest_conf_l−0.1 · S: px>highest_conf_h+0.1; B_SNEO giữ S_BREAK cũ) · TIME 10′ chỉ PnL≥0 (MOM1; B_SNEO giữ vô điều kiện) · không state mới | ✅ CODED 14/10 (`sculp_strategy.py` decide + `config.py` PSL_PTS) — gate like-for-like PASS: V1 −127.91$ ≥ V0-model −232.75$ (Δ +104.83$, 109 lệnh, `_replay_v1.py`) · worst −6.48$ (PSL-cap, G2) · tail 14/10 −9..−12$ → −6.48$ (top-5 delta +3.4..+9.4$) |
| 25 | **S2 EXIT_LOG hygiene + boot-sync (14/10):** dedup keep-earliest-ts (exit_log 134→73 · entry_log 109 không trùng) · `UNIQUE(pos_id)` exit_log+entry_log · tlog `INSERT OR IGNORE` · no-FAIL-row (close-fail → log+Telegram, KHÔNG ghi row; executor `exit()` → `(pnl, ok)`) · EXIT_SYNC row cho pos broker-đã-đóng (synced_exits) · boot `boot_exit_log_sync()` (deals RPC từ ROL gần nhất, magic 20261013, best-effort không crash boot) · xoá file rác `data/sculp5.db` (0B) | ✅ CODED 14/10 (`migrate_s2.py` · `test_s2.py` 9/9 PASS · backup `data/sculp5.db.bak-s2-1014`). ⚠ BACKLOG: CLOSE-FAIL retry cap 2 (§13.2) — hiện = retry tick kế tiếp, chưa cap |
| 26 | **ROLLING-5M = THAM CHIẾU, KHÔNG GATE (user duyệt 14/10):** rolling-5m = 4×m1-đóng + m1-đang-đóng (live) → tag chart (LAYER L2) + KPI/cross-check offline ("m1-zone strong × 5m-pivot overlap → BOUNCE%") — **KHÔNG gate entry/exit** (đúng bucket row 22 "VẠCH + TAG, KHÔNG GATE") · Lý do: fractal ±2 trên 5m vẫn cần 2 nến-5m PHẢI hoàn chỉnh (confirm ≈10–15′, đo 15–25′) → rolling chỉ sớm được 0–5′ cái nhìn in-progress, KHÔNG sớm được confirm · "nhận biết pivot sớm + không mua đỉnh/bán đáy" = khung **M1±2 (row 17, confirm ≈2′)** + gates **G2-LVL/M0** (chặn entry) + exits **PSL/S_BREAK** (không ôm khi break) — tag 5m chỉ là lớp quan-sát người + input tune REV-SAU (bắt buộc qua replay) | ✅ CHỐT 14/10 (BACKLOG: wave L2 sau ship V2, cùng backfill 1h/4h/D1 row 22; m5 data sẵn trong DB) |
| 27 | **V2 ENTRY UNIVERSE = FADES CHỈ (user confirm 14/10):** v0-pullback-fade (gated G2-LVL) + R1/R2 stall-fade (gated M0) · **with-trend/break-ride (B sau close-H / S sau close-L) = KHÔNG nằm trong arm set V2** (chưa thiết kế, chưa có evidence E6) · trong vùng G2+IMPULSE = không entry nào (by design, chi phí đã đo: G2 net −0.37$/1.5d ≈ trung lập · M0-gate sửa 10/12 −61.68$) · muốn thêm break-ride = REV-SAU qua replay (row 26 discipline) | ✅ CHỐT 14/10 |

### 14.1 — Cổng E6 (Luật 9, bổ sung vào §8): replay 12 ngày R1/R2 + G2-LVL trên M1-ladder
- WR theo regime (M0) · số lệnh v0 bị chặn · PnL hợp ≥ baseline v0 (v0 thật chỉ có 13/10→14/10, dedup +21.89$; R1/R2 replay chạy trên toàn m1 có trong DB — cần verify độ phủ, §14.2 bước 4) ·
  threshold 2.5pts / STALL-3nến / touches≥2 / DEAD-2.5 = KHỞI ĐIỂM TUNE (replay quyết, không phải chân lý — §10.2) · chạy cả 2 biến thể: G2-LVL (LVL+EXT15) vs LVL-only để E6 quyết.

### 14.3 — KẾT QUẢ E6 (14/10, `logs/replay_lvl_12day.txt`, proxy m1 + spread 0.24pts)
- **R1/R2 (9 phiên giao dịch 02/10→14/10, 10/03-04 & 10/10-11 = weekend):**
  1 700 lệnh · PnL **+350.88$** · WR **70%** (1190/1700) · trung bình ≈ +39$/phiên.
  Ngày âm: 10/08 (−10.78$), 10/12 (−61.68$, WR 55% — phiên đảo trend mạnh, fade chống dòng). Ngày tốt: 10/13 (+80.39$, WR 78%), 10/07 (+45.94$).
  → **QUA CỬA PILOT** (kỳ vọng dương, WR ≥ 65% ≥ baseline v0 66%… so với baseline v0 48/73 = 65.8% — ngang).
  ⚠️ caveats (chưa đo): proxy m1 (chưa tick-stall) · chưa gate M0 regime · chưa tương tác EDGE/K_eff · 10/12 = chế độ R1/R2 bị punish khi trend-impulse (cần M0 gate chặn R1/R2 trong IMPULSE — spec §12 #12).
- **G2 (cửa v0, 13/10→14/10 chỉ — v0 chỉ tồn tại từ 13/10):**
  A (LVL+EXT15): chặn 63 · cf +22.26$ · B (LVL-only): chặn 53 · cf +21.18$ → **GIỮ G2-A** (EXT15 marginal +1.08$).
  Giá trị thực = chặn tail nặng (07:05 S −12.01 · 02:27 ×2 −2.61 · 01:43 −4.01) đổi lại phí small-win (10:10 S +2.53…) → net ≈ +0.37$ (gần trung lập trên sample 1.5 ngày → LIVE shadow 1-2 tuần đo tiếp, không chặn ship).
- **ĐIỀU KIỆN SHIP (nối §12):** R1/R2 + M0-GATE (impulse-blocking) + G2-A + PSL −6$ + rev 6 layers → replay V2-TOÀN-TRÌNH trên 12 ngày (tick-level) ≥ counterfactual +22.26$/cửa-v0 + PnL R1R2 × (K_eff factor) → kill v0.
- Đo pilot 1 ngày (10/14, proxy m1 + warmup 300′, spread 0.24pts — `logs/replay_lvl_1014.txt`):
  G2-LVL(A) chặn 63 lệnh v0 (trốn lỗ −70.26$ / phí win +69.89$ → net −0.37$) ·
  R1/R2: 80 lệnh +64.99$ (WR 78%) · counterfactual v0−chặn+R1R2 = +87.26$ (v0 thật = +21.89$).
- ⚠️ 10:09 S @4163.01 (−11.41$): G2-LVL **KHÔNG chặn được** (tất cả H-zone trong 2.0pts đã dead — giá xuyên qua; EXT15 4165.60 cách 2.59 > 2.0) → đây là case "dead-zone + đuổi giá" thuộc lớp **PSL −6$ + TIME 10′ (rev 6)** (cắt −11.41 → ≈ −6.00, cứu ≈ 5.4$).
- 01:38 S (−8.90) thuộc M0 V-REV (rev 6) · 07:05 S (−12.01) G2-LVL chặn ✓ (LVL 4157.22) · R1/R2 over-trade tại cụm zone dày (01:10 ×4, 07:04-10 ×4) — live sẽ giới hạn bởi K_eff; E6 đo cả với cap.

### 14.2 — THỨ TỰ CODE (nối tiếp §12, rev 7)
1. `src/lvl.py`: LVL builder (M1 ±2 rolling + touches + strong + broken) + bảng DB `lvl` + rebuild-from-DB (boot).
2. R1/R2 + G2-LVL trong ENTRY (song hành EDGE hiện tại, chung cap K_eff) · config +9 hằng (LVL_TOUCH=2 · LVL_BAND=0.5 · ZONE_PTS=0.5 · ZONE_SPAN=30 · STALL_M1=3 · FADE_PTS=2.5 · LVL_DEAD=2.5 (close-based) · LIMIT_TTL=15 · G2LVL_PTS=2.0 (nhánh LVL không điều kiện nến; EXT15 giữ 2-nến)).
3. LAYER L2 trên chart text-box (vạch ═/─ + tag reference m15/1h/4h) + KPI box theo §14.
4. BACKFILL 1h/4h/D1 (gap_filler multi-TF) → mới bật KPI khung reference.
5. Replay 12 ngày (E6) → ship = kill v0 (Luật 23), verify boot + PID-FILE + probe balance.

---

## 13. NO-STOP ENTRY + CLOSE-FAIL FIX + EXIT_LOG integrity (rev 6.1b · DUYỆT 14/10 · 13.2/13.3 CODED = S2 14/10 · 13.1 KPI-ALARM chưa code — scope dashboard)

### 13.1 NO-STOP ENTRY (lệnh CHAIRMAN: "không dùng entry")
- Bố DAILY_LOSS_STOP $30 entry-halt. Bot không bao giờ dùng entry vì day$ (day$ = sum exit_log dedup).
- Evidence 14/10 09:54: halt bị tất khi day$=-41.34$ — biển đo SAI: (a) PnL không dedup (4869809349 ×10 row, 4869939838 double OK+FAIL), (b) row FAIL vẫn được ghi exit_log.
  Trong khi đó day$ THỲT (dedup) ≈ +11..15$ (vịn xanh) → halt = thiếu hạu quả + bỏ một phạn phục hồi 09:54→09:57.
- Thay vào: KPI ALARM (không stop): day$-dedup ≤ -30$ → Telegram WARN · ≤ -50$ CRIT · ≤ -75$ FUSE (FUSE chỉ nội K_eff xuống 1/2, không stop entry — FUSE default = TẦT).
- PhỒng vệ risk thỲc (thay cho daily-stop) = 4 lớp đã chốt: PSL -6$ (mỗi lệnh) · REVERSE -3$ (mỗi vị thằ) · K/K_eff cap số vị thằ · TP 1.5 + ROL 21:45Z.
- Biển day$ cho mệi threshold/KPI = exit_log DEDUP theo pos_id (row OK only).

### 13.2 CLOSE-FAIL FIX (evidence: 09:55 loop 4869939838 ×6 "Position not found" + RECOVER loop)
1. "Position not found"/"Invalid position" → re-query broker position list:
   · position biến mất (broker đã đóng) → ghi row exit reason='SYNC_BROKER' (pnl từ deal, UNIQUE pos_id idempotent) → drop khoân trạng thại.
   · position vịn còn (giỉn đoân) → retry close, TỐI ĐA 2 lạn liến tiếp cứng pos.
   · vẫn thất bại → drop khoân state + pending-sync (boot EXIT_LOG-SYNC kặt lại) — không vào vỒng lằp.
2. RECOVER "enter missed tracking": lấy entry_ts/px Tị BROKER (openTime/price) — không tạo lại.
3. Row close FAIL: tuyện đối không vào exit_log (chỉ KPI log).

### 13.3 EXIT_LOG integrity + PID-FILE
- Table migration: UNIQUE(pos_id) · INSERT OR IGNORE khi sync · mệi sum PnL (day$, KPI, replay) = dedup theo pos_id (giẫ row OK ts-sỚm-nhất).
- PID-FILE: ghi PID khi khởi tạo, xóa sạch khi thỐi (quan sát 14/10 09:59: pid file mất → PID 2379 not tracked).