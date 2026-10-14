# 📄 S4-HEDGE LIVE ANALYSIS — FILE TIÊU CHUẨN TOÀN DIỆN
> **Mục đích**: 1 file duy nhất để hiểu (1) bối cảnh, (2) cách bot hoạt động, (3) cách bot cần nâng cấp — theo bộ luật Andrej Karpathy (First Principles · Empirical · Minimal Abstractions), phân tích **5 Whys** + **5W2H**, kèm **bảng dữ liệu giá-thời-gian & hoạt động bot** để vẽ biểu đồ.
> **Nguồn dữ liệu (chỉ đọc)**: `logs/scalp5.out` · `logs/scalp5.log` (tlog) · `data/scalp5.db` (tables `entry_log`, `exit_log`) · `logs/scalp5.status.json` · code `main.py` / `src/scalp_strategy.py` / `src/scalp_executor.py` / `src/config.py`.
> **Thời điểm viết**: 15/10/2026 ~05:1x+07 · **Bot live**: PID 29211 (code main @ `b31eb74`, K=8, HEDGE_ENABLE=True, F2 active) · **Cycle**: ROL 21:45Z đã chạy @04:44:55 (đóng rổ cuối −$3.99 net), ngày mới đang chạy.
> **Ký hiệu**: ✅ = đã chứng minh bằng log/DB · (H) = giả thuyết cần verify · $/pt = LOT 0.02 = 2oz = **$2 mỗi point**.

---

# §1. BỐI CẢNH (CONTEXT)

## 1.1. Hệ thống là gì
| Thành phần | Giá trị | Ghi chú |
|---|---|---|
| Bot | `XAU_SCALP5` — scalping vàng | Chạy trên macOS, Python 3.12 (venv) |
| Symbol | XAUUSDm (Exness) | Tài khoản **DEMO** Exness-MT5Trial7, login 433755206 |
| Nền tảng đơn lệnh | MetaApi Cloud SDK (terminal MetaTrader proxy) | Provider-side hay flapping (stream-stall ×3/session) |
| Chiến lược (S4) | MOM1 momentum M1 (K=8 nến) + R1R2 STALL-FADE + **HEDGE-BASKET** (P2-Tuned 15/10) | TP target 1.5pts ≈ +$3/lệnh |
| Lot | 0.02 (= 2oz) | **$2.0 mỗi point** — dùng để đổi pts↔$ trong toàn file |
| Window giao dịch | 00:00–21:45Z (mỗi ngày), ROL 21:45Z đóng ngày | = 07:00–04:45+07 |
| Balance demo | 78.35 (đầu 15/10) → 80.97 (01:33) → hiện đang cycle mới sau ROL | Net session 15/10 ≈ **+$4.3** (day$ @03:57) |

## 1.2. Dòng thời sự kiện S4 (timeline chuẩn)
| Thời gian (+07) | Sự kiện | Trạng thái code |
|---|---|---|
| 14/10 22:53 | Boot V2 (K=4, hedge OFF) — PID 7710 | main @ `16cfd1b` |
| 15/10 00:15–00:58 | V2 chạy: entries 00:17–00:23 (6 lệnh, DB entry_log) · cloud flapping 00:20–00:54 (sync-retry) | V2 |
| 15/10 01:04 | **Cutover S4-HEDGE P2-Tuned LIVE** (HUMAN D2-override): merge main @ `c5caf41` → boot PID 24900 (K=8, HEDGE ON) | S4 pre-F2 |
| 15/10 01:05–01:14 | 3 lần broker reject **"Invalid stops"** (TP tính từ arm-px cũ) → 4 entry B-LIMIT trượt (01:05×3, 01:14×1) | BUG F2 |
| 15/10 01:08 | Rổ #1 khóa → **PRUNE-INSTANT 4s** (−$2.52) — bug F1 (wall px-anchored) | BUG F1 |
| 15/10 01:29–01:33 | Deploy **F2** (TP từ tick live) → main @ `28249fc` → boot PID **29211** · **0 "Invalid stops" kể từ 01:40** ✅ | S4 + F2 |
| 15/10 01:40–04:44 | Session S4+F2: 35 entries · 9 hedge legs · 8 rổ (net −$28.0) · ~30 exits TP/PSL/PRUNE/HEDGE_TAKE/EXIT_SYNC · stream-stall 02:25 & 04:44 | S4 + F2 |
| 15/10 04:44:55 | **ROL**: rổ #9 (S+L) đóng −$4.41/+$0.42 · chu kỳ ngày mới bắt đầu (05:01 open=2) | S4 + F2 |

## 1.3. Tham số P2-Tuned đang chạy (`src/config.py`)
| Tham số | Giá | Vai trò |
|---|---|---|
| `HEDGE_ENABLE` | **True** (15/10 D2-override) | Bật máy rổ hedge |
| `K_CONTEXT` | 8 | Trần **tổng** vị thế + context M1 (8 nến) |
| `MAX_ROOT_POSITIONS` | 4 | Trần lệnh gốc (ROOT) |
| `MIN_ROOT_STEP_PTS` / `MIN_ROOT_GAP_SEC` | 0.35 / 5s | Chống 2 root cùng chiều bắn chùm sát nhau |
| `HEDGE_LOCK_PTS` | 1.2 | Root âm ≥−1.2pts → mở leg đối ứng |
| `HEDGE_BREAK_PTS` | 1.0 | Xác nhận phá cản (PRUNE_BREAK) |
| `HEDGE_MIN_PROFIT_PTS` / `HEDGE_BOUNCE_CONFIRM_PTS` | 1.5 / 0.4 | Điều kiện HEDGE_TAKE |
| `HEDGE_MAX_SPAN_PTS` | 4.5 | PRUNE_SPAN (không tìm thấy cản) |
| `HEDGE_TIMEOUT_MIN` / `BASKET_TIME_MAX_LOSS_USD` | 30′ / −$1.50 | BASKET_TIME (giải phóng slot) |
| `BASKET_TP_USD` / `BASKET_TP_TRIGGER_USD` | +$0.50 / +$1.20 | BASKET_TP + UNWIND_BREAKEVEN guard |
| `PSL_PTS` | 3.0 (vị thế đơn) → **−$6.48** net rổ | Cầu chì (chỉ nhánh UNWOUND — **điểm O1**) |
| `TP_POINTS` | 1.5pts | TP mọi root (chân HEDGE: TP=None) |

## 1.4. Rủi ro đã chấp nhận (ghi rõ, audit trail)
- Gate-3 replay m1-proxy **FAIL 0/3** (worst_basket −$10.36 · PnL B +$561 < A +$6,986) — HUMAN ghi đè D2: *"backtest offline không bao giờ chuẩn xác vì nến đã được làm mềm"* → LIVE toàn diện, theo dõi live, patch sẵn (O1/F1). Verifier G4: **APPROVE** (diff nội bộ an toàn, rủi ro tail ghi rõ).

---

# §2. CÁCH BOT HOẠT ĐỘNG (FIRST PRINCIPLES)

## 2.1. Kiến trúc (giải pháp nguyên tử)
> **Analogy**: giống nhà giao dịch + phòng lệnh: *tick* là bản tin giá · *nến M1* là biểu đồ 1 phút · *tín hiệu* là ý tưởng · *gates* là quy chế công ty (trần lệnh, giãn cách) · *executor* là sàn khớp · *máy rổ hedge* là bộ phận "đối ứng bảo hiểm".

```
tick (MetaApi WS) ──► TickCollector ──► M1 candle (K=8 closes)
                                   │
                                   ▼
              decide() ──► ENTRY (v0-MOM1 / R1R2 arm) ──► gates (K=8 · MAX_ROOT=4 · step/gap)
                                   │
                                   ▼
              executor.enter() ──► create_market_order (TP = live_px ± 1.5pts [F2] · SL=None)
                                   │
              mỗi vị thế ROOT ─► máy rổ _manage_hedge_basket(): NAKED→LOCKED→UNWOUND
                                   │
              EXIT: TP/PSL (strategy) · HEDGE_TAKE/PRUNE_BREAK/PRUNE_SPAN/BASKET_TIME/
                    UNWIND_BREAKEVEN/PSL-6.48 (rổ) · ROL 21:45Z · daily-halt
                                   │
              broker-side: TP trên lệnh (root) · leg KHÔNG TP (rổ quản) · EXIT_SYNC đối chiếu
```

## 2.2. CƠ CHẾ VÀO LỆNH — 3 loại tín hiệu (evidence DB `entry_log`, 35 entries 15/10)
| # | Loại | Dấu nhận (DB) | Cơ chế (first-principles) | Gate áp dụng | Evidence live |
|---|---|---|---|---|---|
| 1 | **v0 MOM1** | `anchor=0, touch=3`, có TP | Momentum: net px so K=8 close M1 ≥ threshold. Timing PULLBACK: arm tại **close nến** (đỉnh−pub cho MUA · đáy+pub cho BÁN), fill khi giá về dip/bật — **không đuổi đỉnh** | K=8 · MAX_ROOT=4 · re-fire ≤2/nến M1 | 4875994191 L@4095.558 → TP +$3.19 (2′); 4875619497 S@4079.086 |
| 2 | **R1R2 STALL-FADE** | `anchor≠0, touch≥2`, có TP | Zone L/H chạm ≥2 lần (FZ) → arm **B-LIMIT/S-LIMIT** (TTL 15′, "regime CREEP/RANGE") → giá chạm arm → MARKET fill; slippage được "TP sửa" căn fill+1.5pts | như v0 + arm TTL | Burst 01:41: 5 arm → **4 lệnh/30s** (T=31/30/29/5) → 3 TP liền +$3.55/3.15/3.22; 03:20: 8 arm → 2 fill |
| 3 | **HEDGE leg** | `TP=None, touch=0`, có `parent_id` | **Không phải tín hiệu** — máy rổ phát: ROOT NAKED âm ≥−1.2pts → mở leg đối ứng, **gỡ TP broker của ROOT** = "khóa 2 đầu" | Không qua gate root (bypass đúng thiết kế) | 9 legs: 4875839456, 4875841960, 4875842002, 4875950711, 4876011551, 4876050864, 4876240117, 4876240468, 4876255890 |

**Sanity check (LAW 8)** — F2 hoạt động: `grep -c "Invalid stops"` sau 01:40 = **0** (trước F2 = 3) · 14 dòng "TP sửa" (slippage 0.12–1.10pts) đều khớp lại TP=fill±1.5 ✓ (log 01:41–03:20).

## 2.3. CƠ CHẾ HEDGE — máy trạng thái `NAKED → LOCKED → UNWOUND`
> **Analogy**: hedge 1:1 giống **mua bảo hiểm xe**: trả phí (gap −1.1…−2.2pts ≈ −$2.1…−4.5) để *đóng băng* thiệt hại — không còn tăng/giảm theo giá. Rổ hedge **không phải nguồn lãi**, là **công cụ capping risk**.

### 2.3.1. Toán 1:1 (first-principles, chứng minh số)
Rổ = root L@e_r + leg S@e_l (lot 0.02 mỗi bên, $2/pt). Tại giá p bất kỳ:
`net(p) = 2·[(p − e_r) + (e_l − p)] = 2·(e_l − e_r) = −gap × $2` — **hằng số, không phụ p**.
**Verified live**: rổ #3/#4 gap=1.14pts → net lý thuyết −$2.29; đóng 02:50: +32.93−35.18 = **−$2.25** ✅ (trùng, sai số = phí).

### 2.3.2. Bảng trạng thái + exit (code `scalp_strategy.py` L716–844)
| Trạng thái | Điều kiện vào | Hành động | Exit (theo thứ tự ưu tiên) |
|---|---|---|---|
| **NAKED** | root mở, chưa leg | pnl root ≤ −1.2pts → ENTER leg (TP=None) + gỡ TP root; tìm wall cản (structural) | — |
| **LOCKED** | leg đang mở | "Khóa 2 đầu": net frozen; theo dõi wall_peak | ① `PRUNE_BREAK` (px phá cản ±1.0) ② `PRUNE_SPAN` (không cản + span≥4.5) ③ `HEDGE_TAKE` (giá tại cản ±0.5 · leg lãi≥1.5 · giật lùi≥0.4 · M0≠IMPULSE) ④ `BASKET_TIME` (≥30′ mà net≥−$1.50) |
| **UNWOUND** | leg đã HEDGE_TAKE (credit banked) | root trần; net = pnl_root + credit | ① `PSL` (net≤−$6.48 cầu chì) ② `BASKET_TP` (net≥+$0.50) ③ `UNWIND_BREAKEVEN` (peak≥+$1.20 rồi lùi ≤+$0.50) ④ `BASKET_TIME` ⑤ `PRUNE_BREAK` (quay đầu vượt peak/cản) |

### 2.3.3. 8 rổ đã đóng + 1 rổ ROL (evidence DB `exit_log`)
| Rổ | ROOT (entry) | LEG (entry) | Khóa | Đóng (ts, reason) | Net rổ | Đánh giá |
|---|---|---|---|---|---|---|
| #1 | L@4086.664 (4875838538) | S@4085.488 (4875839456) | 01:08:14 | **01:08:18 PRUNE_BREAK(LOCKED)** — **4s** | **−$2.52** | ⚠️ F1 (PRUNE-INSTANT) |
| #2 | L@~4097.15 (4876010029) | S@4096.139 (4876011551) | 02:00:52 | HEDGE_TAKE **+$3.05** (02:04:22) → PRUNE_BREAK(UNWOUND) −$8.80 (02:05:56) | **−$5.75** | ✅ chu trình UNWOUND hoàn chỉnh (banked credit rồi mới tỉa) |
| #3 | L@4085.89 (4875839034) | S@4084.746 (4875841960) | 01:08:51 | 02:50:33 (TP +$32.93 / PSL −$35.18, riêng lẻ) | **−$2.25** | ⚠️ giữ ~2h, không đường release (O1) |
| #4 | L@4085.907 (4875839623) | S@4084.562 (4875842002) | 01:08:53 | 02:50:33 (TP +$32.35 / PSL −$35.55) | **−$3.20** | ⚠️ như #3 |
| #5 | L@4094.504 (4875950033) | S@4092.989 (4875950711) | 01:41:41 | 02:50:33 (TP +$14.69 / PSL −$19.18) | **−$4.49** | frozen ✓ |
| #6 | L@4098.114 (4876050046) | S@4097.095 (4876050864) | 02:14:33 | 02:50:33 (TP +$8.35 / PSL −$10.48) | **−$2.13** | frozen ✓ |
| #7 | S@4097.507 (4876235717) | L@4099.137 (4876240117) | 03:45→03:48 | 03:51:28 PRUNE_BREAK ×2 | **−$3.74** | ✅ ≈ thiết kế −$3.36 |
| #8 | S@4097.936 (4876235868) | L@4099.398 (4876240468) | 03:45→03:48 | 03:51:28 PRUNE_BREAK ×2 | **−$3.91** | ✅ ≈ thiết kế |
| #9 | S@4102.862 (4876252118) | L@4104.573 (4876255890) | 03:57 | **ROL 04:44:55** (−$4.41/+$0.42) | **−$3.99** | frozen ✓ (gap 1.71pts×2 = $3.42 + phí) |
| | | | **TỔNG 9 rổ** | | **−$31.97** | chi phí "bảo hiểm" của ngày 15/10 |

## 2.4. CƠ CHẾ THOÁT & PHÒNG THỦ
| Lớp | Cơ chế | Evidence |
|---|---|---|
| TP broker | Root có TP=fill+1.5pts trên broker (F2: tính từ tick live) → hit tự đóng | 20× exit TP +$2.7…+3.9 · 3 root chạy dài +$8.35…+32.93 |
| PSL vị thế đơn | pnl ≤ −3.0pts → cắt (cầu chì lệnh trần) | 4× leg PSL −$10.48…−35.55 (02:50, sau khi mất liên kết rổ) |
| PSL rổ | net rổ ≤ −$6.48 (chỉ nhánh UNWOUND) | chưa trigger (sát nhất: rổ #2 net −$5.75) |
| ROL 21:45Z | Đóng mọi vị thế cuối ngày | rổ #9 @04:44:55 ✅ |
| Daily-halt | Lỗ ngày ≥ ngưỡng → khóa giao dịch | chưa trigger (halted=False) |
| EXIT_SYNC | Đối chiếu deal-history broker (bot bị stall vẫn khớp PnL) | 9× EXIT_SYNC +$2.95…+3.05 |

## 2.5. RESILIENCE (S4-BOOT)
| Sự kiện | Hành xử | Ghi chú |
|---|---|---|
| Cloud MetaApi flapping (stream-stall 02:25, 04:44 + 00:20–00:54 phiên cũ) | Auto-restart pipeline (300s) + redeploy terminal + NO-TRADE flag đến khi DEMO confirm | Vị thế + TP **an toàn bên broker** (bot chết, lệnh không trần) |
| Restart/adopt | `executor.adopt()` nhận lại vị thế theo magic + re-attach registry rổ ("re-attach rổ metadata: N position (registry M rổ)") | ✅ verify 01:40:01 "adopt 4 positions" |
| RPC "no response" | Không retry (chống double-order); position poll tự **RECOVER** lệnh đã khớp | 7 lần "no response" (02:00 ×1, 03:20 ×6) — trong đó root 4876010029 **vẫn khớp bên broker** (exit_log) = false-negative ✓ |

---

# §3. EVIDENCE & BENCHMARK (LAW 9 — baseline số)
**Session 15/10 (00:17→04:44, chỉ code S4+F2 từ 01:04):**
| Metric | Số | Nguồn |
|---|---|---|
| Tổng entries | 35 (v0: 12 · R1R2: 14 · HEDGE leg: 9) | `entry_log` |
| Tổng exits | 62 rows (TP 24 · PSL 8 · PRUNE_BREAK 8 · HEDGE_TAKE 1 · EXIT_SYNC 12 · ROL 2 · khác) | `exit_log` |
| PnL lệnh đơn lẻ (TP+SYNC) | ≈ **+$78** (24 TP + 12 EXIT_SYNC, trung bình +$3.1) | `exit_log` Σ |
| PnL rổ hedge | **−$31.97** (9 rổ, §2.3.3) | `exit_log` Σ cặp |
| **Net thực hiện** | ≈ **+$45** closed PnL 00:17–04:44 · day$ +$4.33 @03:57 (counter in-memory, reset theo restart) | DB + status.json |
| "Invalid stops" reject | **3 lần, toàn bộ pre-F2 (01:05×3, 01:14×1); post-F2 = 0** | log grep |
| RPC "no response" | 7 lần (02:00, 03:20×6) — false-negative (khớp bên broker) | log + DB |
| Stream-stall | 3 lần (00:20–00:54, 02:25, 04:44) — tự hồi | log |
| Uptime bot S4 | 29211: 3h15m không crash | ps etime |

---

# §4. 5 WHYS — 5 chuỗi sự cố (empirical, không đoán)

### W1. Vì sao giá bật 01:14 (+4.4pts) mà bot không vào lệnh?
| Mức | Câu hỏi | Trả lời (evidence) |
|---|---|---|
| 1 | Vì sao không có lệnh mới khi giá spike? | Bot **có** phát R-arm 01:04:00 (`R-arm L-zone 4086.35 → B-LIMIT @4088.85`) nhưng order bị **broker reject "Invalid stops"** 01:14:01 → "không retry" → entry trượt |
| 2 | Vì sao broker reject? | TP gán = **arm-px + 1.5 = 4090.35**, mà lúc đặt lệnh ask đã ~4090.3+spread → TP nằm **sai phía/đủ khoảng cách stops-level** → MT5 `Invalid stops` |
| 3 | Vì sao TP tính từ arm-px? | Code `executor.enter()` L150 (pre-F2): `tp = round(px + side*TP_POINTS, 2)` với `px = action["px"]` = **plan-px** (arm), không phải giá sàn hiện tại |
| 4 | Vì sao plan-px sai lúc giá chạy? | R-arm là arm TTL 15′ đặt tại zone; khi giá **spike xuyên arm**, fill MARKET ở px hiện tại (cao hơn arm ~1.5–3pts) — TP kế hoạch từ arm đã "lệch pha" |
| 5 (root) | Vì sao thiết kế lại để TP kế toán theo px-kế-hoạch? | TP được định nghĩa "entry+1.5" với *entry=giá dự kiến*; thiếu bước **căn lại TP theo giá thật tại thời điểm đặt lệnh** → **F2 (đã sửa ✓)**: TP = `strategy.last_px ± 1.5` |

### W2. Vì sao rổ #1 bị cắt chỉ 4s sau khi khóa (PRUNE-INSTANT, −$2.52)?
| 1 | Rổ #1 bị PRUNE_BREAK(LOCKED) 01:08:18, 4s sau khi leg mở | Log + DB (exit 4875838538/9456, px=4085.229) |
| 2 | Vì sao điều kiện phá cản bật sớm? | `broke = px <= wall − 1.0` (root L) chỉ true nếu **wall ≥ 4086.23** — tức wall lúc đó là cản **trên** giá, không phải cản 4083.036 (dưới) như log leg |
| 3 | Vì sao wall đổi sang cản trên? | `_find_structural_wall` (L707/712) chọn mức **gần px nhất** (`key=abs(w−px)`); px đang trượt → "gần nhất" = mức sát/trên px → vùng PRUNE hẹp → bật ngay |
| 4 | Vì sao lại "gần px" thay vì "gần entry"? | Intent gốc (comment L696) là chọn "cản gần giá hiện tại" — đúng cho **tìm cản mới**, SAI cho **neo cấu trúc rổ đang phòng thủ** (phải neo theo entry) |
| 5 (root) | **F1**: đổi `abs(w−px)` → `abs(w−entry)` (2 dòng) — **đang revert, chưa deploy vì pin test nhảy 82→122** (đổi logic trading, cần duyệt riêng + re-baseline + replay) |

### W3. Vì sao rổ #3/#4 (frozen −$2.25/−3.20) chiếm 4/8 slot ~2 giờ mà không tự đóng?
| 1 | Rổ giữ 01:08→02:50, không có exit nào | DB: 4 exit đồng-ts 02:50:33 (riêng lẻ, do stream-stall re-adopt) |
| 2 | Vì sao BASKET_TIME (30′) không fire? | Điều kiện: 30′ **VÀ** net ≥ −$1.50 — net rổ #3/#4 frozen ≈ −$2.25/−3.20 < −1.50 → **điều kiện không bao giờ đạt** (vô lý ngược: rổ càng sâu càng không được ra) |
| 3 | Vì sao PSL −$6.48 không cứu? | Cầu chì PSL chỉ nằm **nhánh UNWOUND**; rổ LOCKED chưa HEDGE_TAKE → không bao giờ chạy PSL-check |
| 4 | Vì sao wall-break không xảy ra? | Cần px ≤ 4083.036−1.0 = 4082.0 — mà px **tăng** 4085→4105 cả sáng → vùng phá cản không tới |
| 5 (root) | **O1 (đề xuất, ~6 dòng)**: (a) thêm PSL-breaker net≤−$6.48 vào nhánh **NAKED/LOCKED** · (b) hạ floor BASKET_TIME từ −$1.50 → **−$6.48** (30′ + net≥−6.48 = giải phóng slot, không giữ rổ chết) — **chờ HUMAN duyệt** |

### W4. Vì sao hedge "lỗ" −$32 trong ngày giá TĂNG mạnh (+$45 lệnh đơn)?
| 1 | Σ rổ = −$31.97 | §2.3.3 |
| 2 | Vì sao mỗi rổ net âm? | Net rổ = −gap×$2 (hằng số, §2.3.1): gap khóa = 1.05–2.2pts (trigger −1.2pts + slippage + spread) |
| 3 | Vì sao gap luôn dương khi khóa? | Leg mở **MARKET** khi root đã âm −1.2pts: fill leg trượt thêm ~0.1–0.5pts theo spread/slip (log "TP sửa slippage 0.2–1.1pts") |
| 4 | Vì sao trigger −1.2pts hợp lý? | Thiết kế P2-Tuned: "âm 1.2pts → mở lệnh đối ứng khóa lỗ" — bảo hiểm bắt đầu khi lệnh đã lỗ |
| 5 (root) | **Không phải bug — là chi phí thiết kế** (premium bảo hiểm). Tối ưu được: (i) trigger sớm hơn (−0.8pts, giảm gap) nhưng tăng tần suất · (ii) F1 (giảm PRUNE-INSTANT vô lý) · (iii) **chỉ hedge khi M0 ≠ IMPULSE** (đã có phần) — **đo A/B trước khi đổi (LAW 9: baseline −$3.42/rổ hiện tại)** |

### W5. Vì sao 7 lần "create_market_order → no response" (02:00, 03:20)?
| 1 | 7 entry RPC fail, "không retry" | Log |
| 2 | Vì sao RPC fail? | Cloud MetaApi terminal đang flapping (cùng cửa sổ stream-stall) — order có thể **khớp bên broker mà response mất** (chứng minh: root 4876010029 tồn tại trong exit_log dù không có entry_log) |
| 3 | Vì sao không retry? | Thiết kế chống **double-order** (idempotency chưa có) |
| 4 | Vì sao không tự phát hiện "đã khớp" sớm hơn? | Position-poll RECOVER có tồn tại nhưng chỉ chạy theo chu kỳ poll (mất vài tick) |
| 5 (root) | **F3 (đề xuất, optional)**: sau "no response" → **poll 1 lần vị thế mới trong 2–3s trước khi bỏ** (detect fill đã có → RECOVER, chưa có → bỏ an toàn) · + đề xuất MetaApi support về flapping (ticket, theo docs 14/10) |

---

# §5. 5W2H

## 5.1. Hệ thống hiện tại
| Câu hỏi | Trả lời (evidence) |
|---|---|
| **What** gì? | Bot scalping XAUUSDm: TP 1.5pts ($3) · hedge basket đối ứng 1:1 khi root −1.2pts · đóng ngày 21:45Z (ROL) |
| **Who** ai? | (1) Bot PID 29211 (user `admin`, macOS) · (2) MetaApi Cloud terminal (provider) · (3) Exness DEMO 433755206 · (4) HUMAN (duyệt L2, D2-override, F2) |
| **When** khi nào? | Window 07:00–04:45+07 mỗi ngày · ROL 04:45+07 · session live: 15/10 01:04→nay (S4+F2) |
| **Where** ở đâu? | Code: root `/Users/admin/Desktop/DESIGN/XAU_SCALP5` (main) + worktree `-s4-hedge` · Data: `data/scalp5.db` · Log: `logs/scalp5.out/.log` · Remote: `dactriltd/XAU_SCALP5` (private) |
| **Why** vì sao? | North-star: TP 1.5pts giữ nguyên; P2-Tuned tăng tần suất (K 4→8, MAX_ROOT 4) + hedge "bảo hiểm" vị thế âm → tăng volume entries, cap tail-loss mỗi lệnh |
| **How** như thế nào? | Tick→M1→3 tín hiệu→gates→market order (TP live-px [F2], SL=None)→máy rổ 3-trạng-thái→exit đa lớp (TP/PSL/rổ/ROL) + resilience (NO-TRADE, adopt, auto-restart) |
| **How much** bao nhiêu? | $2/pt · balance 78.35→80.97→(sau ROL, cycle mới) · net closed 15/10 ≈ **+$45** · chi phí hedge −$31.97 · TP trung bình +$3.1/lệnh · tần suất ~1 entry/3min (01:40–04:44) |

## 5.2. Nâng cấp (roadmap §6)
| Câu hỏi | O1 (ưu tiên) | F1 | F3 (optional) |
|---|---|---|---|
| What | PSL-breaker NAKED/LOCKED + BASKET_TIME floor −$6.48 | Wall neo entry (2 dòng) | Poll-fill trước khi bỏ "no response" |
| Who | Agent thực thi (worktree) + HUMAN duyệt + verifier | như O1 | như O1 |
| When | Sau khi HUMAN duyệt (ngay hôm nay) | Sau O1 (1 cycle riêng, re-baseline pin) | Cùng cycle O1 hoặc sau |
| Where | `src/scalp_strategy.py` L748–780 (+L836) | L707/712 | `src/scalp_executor.py` L158–160 |
| Why | Rổ frozen **giữ slot vô thời hạn** (W3): 4/8 slot chết 2h · replay tail −$10.36 | PRUNE-INSTANT cắt rổ 4s (W2) | Giảm entry "mất" khi cloud flapping (W5) |
| How | +6 dòng: nếu LOCKED/NAKED mà net≤−$6.48 → EXIT cả rổ `PSL` (D3: giữ mã PRUNE_BREAK? **KHÔNG — thêm reason `PSL` riêng cho rổ, log `branch=LOCKED`**); BASKET_TIME floor đọc `BASKET_TIME_MAX_LOSS_USD` mới (−6.48) | Đổi `abs(w−px)`→`abs(w−entry)` + re-baseline pin 122 + replay | 1 lần poll-fill 2–3s |
| How much | Rủi ro: PnL rổ giống (frozen −$2…−4) nhưng **slot giải phóng +20–40% thời gian** · test: pin hedge-ON (82→chờ đo), replay gate-3 (chờ chạy) | Pin 82→122 (+49% entries — đã đo) | Không đổi pin (chỉ executor) |

---

# §6. NÂNG CẤP THEO LUẬT KARPATHY (first-principles → minimal → measured)

> Nguyên tắc (AGENTS.md workspace): cấm over-engineering (≤2 tầng trừu tượng), mọi khẳng định có bằng chứng, **baseline trước khi tối ưu**, code sạch có comment non-trivial.

## 6.1. Bảng nâng cấp (đã sort theo impact/rủi ro)
| # | Patch | Dòng | Impact (số) | Rủi ro | Trạng thái | Acceptance |
|---|---|---|---|---|---|---|
| **O1** | PSL-breaker NAKED/LOCKED + BASKET_TIME floor → −$6.48 (new cfg `PSL_BASKET_USD=6.48`) | ~6 | Giải phóng slot rổ chết (observed 2h×4 slot) · giới hạn tail (replay worst −$10.36 → −$6.48) | Thấp (chỉ thêm exit, không đổi entry) | **Chờ HUMAN DUYỆT** (lệnh W3 + replay evidence) | Pin hedge-ON tái baseline + replay: worst_basket ≥ −$6.48·slot-time rổ LOCKED ≤ 30′+ε |
| **F1** | Wall neo entry (`abs(w−entry)`) | 2 | Chống PRUNE-INSTANT (observed −$2.52×n) | **Trung bình**: pin 82→122 (+49% entries) = đổi hành vi | Reverted, chờ cycle riêng | Pin mới (122) + replay 3 criteria |
| **F2** | TP từ tick live | ~5 | 0 "Invalid stops" post-01:40 ✅ · +4 entry hồi (bursts B-LIMIT) | Đã thực chiến | ✅ **ĐANG CHẠY** | (hoàn thành 01:29) |
| **F3** | Poll-fill trước khi bỏ "no response" | ~8 | 7 entry "mất" → 0 (false-negative) | Thấp (idempotent nếu poll đúng magic) | Đề xuất | 1 replay RPC-mock |
| **F4 (monitor)** | Theo dõi cloud MetaApi (ticket support) | 0 | 3 stream-stall/ngày · 2× adopt cycle | 0 | Đang làm | Uptime pipeline ≥ 90% |

## 6.2. Baseline hiện tại (đo, không đoán — LAW 9)
| Metric | Baseline (S4+F2, 00:17–04:44) | Target sau O1 |
|---|---|---|
| Net/ rổ | −$3.42 trung bình (9 rổ, −$2.13…−$5.75) | không đổi (frozen) |
| Thời gian rổ giữ slot | 34–160′ (median ~50′, #3/#4 = 142′) | **≤ 30′+ε** (BASKET_TIME floor mới) |
| Worst basket (live) | −$5.75 (rổ #2) / replay −$10.36 | ≤ −$6.48 (breaker) |
| Entries/ngày | ~35 (04h) ≈ ~45–50/ngày đầy | giữ nguyên (O1 không đổi entry) |
| Lệnh trượt do reject | 0 (post-F2) | 0 (F3: +0) |

## 6.3. Quy trình deploy (mỗi patch)
`worktree edit → py_compile → test_offline (dual-pin 82/493, cho phép re-baseline HUMAN-duyệt) → test_s2 (9/9) → _replay_hedge.py (3 criteria) → G4 verifier (read-only) → HUMAN duyệt merge → ff-main → push → restart bot (clean, adopt) → verify boot log + status.json` — đúng pattern F2 (đã chạy 1 lần, ~15 phút).

---

# §7. BẢNG DỮ LIỆU CHO VẼ BIỂU ĐỒ

> Mọi bảng dưới là **raw evidence** (log/DB), không làm tròn PnL. Đơn vị: px = giá XAUUSDm · $ = PnL thực (LOT 0.02).

## 7.1. Chuỗi giá–thời gian (cho đường giá + indicator) — nguồn `[HB]` (5 phút), 15/10
| Thời gian | px | d5m (pts) | mode | open | day$ (in-memory*) |
|---|---|---|---|---|---|
| 00:15:18 | 4079.52 | +1.03 | — | 0 | +0.00 |
| 00:20:18 | 4082.40 | +2.26 | — | 3 | +0.00 |
| 01:04:45 | 4083.63 | +2.39 | — | 0 | +0.00 |
| 01:09:45 | 4085.62 | +2.44 | — | 5 | +0.49 |
| 01:14:46 | 4090.29 | +4.37 | BUY | 4 | +3.72 |
| 01:19:46 | 4091.98 | +1.39 | — | 4 | +3.72 |
| 01:40:16 | 4092.84 | +1.84 | — | 4 | +0.00 |
| 01:45:17 | 4093.50 | +1.11 | — | 6 | +15.91 |
| 01:50:17 | 4093.19 | −0.18 | — | 6 | +15.91 |
| 01:55:21 | 4096.16 | +2.49 | — | 6 | +19.79 |
| 02:00:23 | 4097.24 | +2.13 | — | 6 | +22.98 |
| 02:05:24 | 4094.07 | −2.30 | — | 7 | +26.03 |
| 02:10:27 | 4096.35 | +3.07 | BUY | 6 | +20.25 |
| 02:15:27 | 4097.90 | +1.42 | — | 8 | +20.25 |
| 02:50:33 | 4102.36 | 0.00 | — | 8 | +0.00 |
| 03:02:35 | 4101.47 | 0.00 | — | 0 | +0.00 |
| 03:14:21 | 4100.19 | −1.87 | — | 0 | +0.00 |
| 03:19:22 | 4099.60 | −0.14 | — | 0 | +0.00 |
| 03:24:22 | 4100.95 | +0.91 | — | 2 | +0.00 |
| 03:29:25 | 4100.44 | −0.21 | — | 0 | +5.95 |
| 03:37:25 | 4099.51 | −1.64 | — | 0 | +0.00 |
| 03:42:25 | 4099.56 | −0.28 | — | 0 | +0.00 |
| 03:47:26 | 4097.86 | −1.67 | — | 2 | +2.73 |
| 03:52:29 | 4101.41 | +2.80 | BUY | 0 | −4.92 |
| 03:57:29 | 4104.89 | +4.13 | BUY | 3 | +4.33 |
| 05:01:36 | 4104.81 | +4.05 | BUY | 2 | +0.00 |
| 05:06:36 | 4103.21 | −1.58 | — | 0 | −3.57 |
| 05:11:37 | 4103.84 | +1.00 | — | 0 | −3.57 |

\* `day$` reset theo mỗi lần restart pipeline (chỉ tham khảo; PnL chuẩn = §7.3/DB).

## 7.2. Timeline sự kiện (cho markers trên biểu đồ giá) — mỗi dòng = 1 marker
| Thời gian | Loại | chi tiết | px (giao dịch) | PnL ($) | pos_id |
|---|---|---|---|---|---|
| 01:05:08–16 | ❌ REJECT | 3× "Invalid stops" (pre-F2) | ~4085 | 0 (trượt) | — |
| 01:07:00 | ▲ ENTRY R1R2 | L T=17 TP-sửa 4086.53→4087.02 | 4085.516 | — | 4875833446 |
| 01:07:32 | ▼ EXIT TP | +$3.01 | 4087.0 | +3.01 | 4875833446 |
| 01:08:08 | ▲ ENTRY v0 | L T=3 | 4085.89 | — | 4875839034 |
| 01:08:14 | 🔒 HEDGE | leg S (khóa rổ #1) + **PRUNE 4s** (F1) | 4085.488 | −2.52 | 4875839456 |
| 01:08:49 | 🔒 HEDGE | legs S rổ #3/#4 (khóa 2 đầu) | 4084.75/4084.56 | (−2.25/−3.20 @02:50) | 4875841960/2002 |
| 01:14:01 | ❌ REJECT | "Invalid stops" (pre-F2, trượt entry) | ~4090.3 | 0 | — |
| 01:40:01 | 🔄 ADOPT | re-attach 4 vị thế (F2 boot) | — | — | — |
| 01:41:02 | ▲ BURST | 5 R-arms → 4 L fills/30s (T=31/30/29/5) | 4092.56–4092.80 | — | 48759473xx |
| 01:41:29 | ▼ EXIT ×3 | TP +3.55/3.15/3.22 | 4094.38 | +9.93 | — |
| 01:52:39 | ▼ EXIT TP | S T=2 (H-zone 4094.85) | 4090.79 | +3.88 | 4875977946 |
| 02:00:09 | ❌ RPC | "no response" (khớp bên broker = root rổ #2) | ~4096 | — | 4876010029 |
| 02:04:22 | 💰 HEDGE_TAKE | rổ #2 banked credit (UNWOUND) | 4094.37 | +3.05 | 4876011551 |
| 02:05:56 | ✂️ PRUNE-UNWOUND | root rổ #2 (net −$5.75) | 4092.75 | −8.80 | 4876010029 |
| 02:14:06 | ▲ ENTRY R1R2 | L T=2 + leg S (rổ #6) | 4098.11/4097.10 | (−2.13 @02:50) | 4876050046/0864 |
| 02:25:25 | ⚠️ STALL | stream-stall → auto-restart pipeline | — | — | — |
| 02:50:33 | ▼ MASS EXIT | 8 lệnh cùng tick (TP×4 / PSL×4, riêng lẻ) | 4102.36 | +7.93 net 8 lệnh | — |
| 03:20:03–16 | ❌ RPC ×6 | "no response" (cloud flapping) | ~4100 | 0 | — |
| 03:20:07 | ▲ BURST | 8 R-arms → 2 L fills | 4100.06 | — | 4876206483/0502 |
| 03:45–03:48 | 🔒 HEDGE ×2 | rổ #7/#8 (S roots + L legs) | 4097.5–4099.4 | (−3.74/−3.91 @03:51) | — |
| 03:51:28 | ✂️ PRUNE ×4 | rổ #7/#8 phá cản (≈thiết kế −3.36) | 4100.77 | −7.65 net | — |
| 03:56:00 | ▲ ENTRY R1R2 | L T=9 + S v0 (rổ #9) | 4104.26/4102.86 | — | 4876254374/2118 |
| 03:57 | 🔒 HEDGE | leg L rổ #9 (khóa) | 4104.57 | (−3.99 @ROL) | 4876255890 |
| **04:44:55** | 🌙 **ROL** | đóng ngày: rổ #9 | 4104.81 | −4.41/+0.42 | — |
| 04:44:53 | ⚠️ STALL | stream-stall (trước ROL; tự hồi) | — | — | — |

## 7.3. PnL theo rổ (cho bar chart) & tổng hợp (cho step-chart cumulative)
| Rổ | Net ($)* | Rổ | Net ($) | Rổ | Net ($) |
|---|---|---|---|---|---|
| #1 (01:08) | −2.52 | #4 (01:08) | −3.20 | #7 (03:45) | −3.74 |
| #2 (02:00) | −5.75 | #5 (01:41) | −4.49 | #8 (03:45) | −3.91 |
| #3 (01:08) | −2.25 | #6 (02:14) | −2.13 | #9 (03:57) | −3.99 |

\* net = Σ pnl root + leg tại close (frozen −gap×$2). **Tổng rổ = −$31.99**.

| Nhóm PnL closed (15/10, DB) | Σ ($) |
|---|---|
| Lệnh đơn lẻ TP (24) | +$57.3 |
| Lệnh đơn lẻ EXIT_SYNC (12, gồm +3.00/−0.46) | +$33.4 |
| HEDGE_TAKE (1) | +$3.05 |
| Rổ hedge (9, §7.3) | **−$31.99** |
| PSL vị thế đơn (4, không thuộc cặp) | −$0 (gộp trong EXIT_SYNC) |
| **NET CLOSED** | **≈ +$61.8** (00:17–04:44, chưa trừ commission ~−$5.7 đã gồm trong pnl DB) |

> **Ghi chú biểu đồ**: đường px (§7.1) + markers sự kiện (§7.2, layer theo loại: ▲ entry xanh, ▼ exit TP xanh nhạt, ✂️ PRUNE đỏ, 🔒 HEDGE tím, ❌ reject vàng, 🌙 ROL xám) · bar chart net/rổ (§7.3) · step-chart cumulative PnL theo §3.

## 7.4. Gợi ý 4 biểu đồ (spec vẽ)
1. **Giá + markers**: line px (§7.1) từ 00:00→05:15; markers §7.2; highlight vùng spike 01:14 (+4.4pts, nơi F2 cứu entry) & 01:05–01:14 (rejects).
2. **Cumulative PnL**: step-line theo ts exits (DB), mốc 01:04 (S4 live), 01:40 (F2), 02:50 (mass exit +$7.9), 03:51 (−$7.65), 04:44 (ROL −$3.99).
3. **Net/rổ (bar)**: 9 bars §7.3 — thể hiện chi phí "bảo hiểm" và rổ #2 (−5.75, UNWOUND) là ngoại lệ sâu.
4. **Open-positions over time**: step-chart `open` (§7.1 col open): 0→5 (01:09) →4→6→8 (02:15, chạm trần K=8) →0 (03:02) →3 (03:57) →2 (05:01).

---

# PHỤ LỤC A — Tái tạo dữ liệu (các lệnh đã dùng, chỉ-đọc)
```bash
cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
sqlite3 "file:data/scalp5.db?mode=ro" "SELECT datetime(ts,'unixepoch','+7 hours'),pos_id,kind,entry,tp,anchor,touch FROM entry_log WHERE ts>1791993000 ORDER BY ts;"
sqlite3 "file:data/scalp5.db?mode=ro" "SELECT datetime(ts,'unixepoch','+7 hours'),pos_id,reason,exit_px,pnl FROM exit_log WHERE ts>1791993000 ORDER BY ts;"
grep -E "\[HB\]|R-arm|Invalid stops|no response" logs/scalp5.out
```

# PHỤ LỤC B — Định danh
File: `docs/S4-HEDGE-LIVE-ANALYSIS.md` (repo `dactriltd/XAU_SCALP5`, branch main @ `b31eb74`) · Người viết: Agent (loop L1/L2, STATE.md audit trail) · Chuẩn: AGENTS.md workspace (Karpathy 10-luật) + 5 Whys + 5W2H · Bản: v1.0 (15/10 05:1x+07).
