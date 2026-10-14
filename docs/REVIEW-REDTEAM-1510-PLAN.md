# 🛡 REVIEW-REDTEAM-1510 — PHÂN TÍCH + PLAN NÂNG CẤP (KHÔNG CODE)
> **Mục đích**: kiểm định độc lập (first-principles, bằng chứng code/log/DB) đối với Red Team Report 15/10 về S4-HEDGE, rồi xuất **plan thực thi** cho 2 phương án (A/B). **File này = PLAN thuần — KHÔNG có diff code** (code sẽ được xuất bản ở cycle L2 riêng, sau khi HUMAN chốt phương án).
> **Nguồn bằng chứng**: `src/scalp_strategy.py` (L664-844 máy hedge + gate root) · `src/scalp_executor.py` (L23-24 day_loss, L276-281 fuse, L24 comment, L61-72 HEDGE lock) · `main.py` (L365-390 re-attach, L632-645 shutdown/stall) · `logs/scalp5.out` · `data/scalp5.db` (entry_log/exit_log) · `config.py` (DAILY_LOSS_STOP=30.0).
> **Giới hạn**: mọi kết luận gắn evidence; chỗ suy luận đánh dấu **(H)**.

---

## §1. KẾT QUẢ KIỂM ĐỊNH RED TEAM — 8/8 claims, đối chiếu code + log + DB

| # | Claim Red Team | Phán quyết của tôi | Bằng chứng định vị (chứng minh được, không phải ý kiến) |
|---|---|---|---|
| **F1** | Bản sửa `abs(w−entry)` **sai toán học, cấm deploy**: wall≈entry → px≈wall−1.2 < wall−1.0 → PRUNE-INSTANT ngay giây 0 (giải thích pin 82→122) | ✅ **ĐÚNG** | Code thực L702-712: filter `w > entry` (S) / `w < entry` (L) nhưng **xếp hạng `abs(w−px)`** → chọn được mức nằm GIỮA px và entry (case thật: root L @4086.664, px=4085.229, wall=4086.35 → `4085.229 ≤ 4086.35−1.0=4085.35` = TRUE → PRUNE 4s). Toán Red Team: neo entry ⇒ wall=E−δ (δ≈0-0.2) ⇒ px=E−1.2 ⇒ margin (1.2−δ) > 1.0 khi δ<0.2 → bùng ngay. Pin 82→122 (+49% lệnh) = hệ quả slot được giải phóng sớm ✓ nhất quán |
| **F1-Directional** | Sửa đúng = bộ lọc HƯỚNG theo px: L-root chỉ nhận cản `w ≤ px−pad` (lấy max), S-root `w ≥ px+pad` (lấy min), pad≈0.3pts; rỗng → trả None (ra nhánh span/time) | ✅ **ĐÚNG** (khác hẳn bản F1 cũ) | At-lock px cách entry đúng 1.2pts ⇒ `w ≤ px−0.3` ⇒ điều kiện PRUNE `px ≤ w−1.0` cần giá RƠI THÊM 1.0pts từ wall → margin an toàn ≥1.3pts ✓. Code L782 sẵn có nhánh `not wall → PRUNE_SPAN ≥4.5pts` + L810 BASKET_TIME làm fallback khi None ✓ (thoạt None an toàn) |
| **O1** | Sàn `−$1.50` BASKET_TIME = **dead code 100%** với rổ frozen (net −$2.13…−$4.49 không bao giờ ≥ −$1.50) | ✅ **ĐÚNG** | L812: `net_lock >= -1.50` · L837: cùng floor cho UNWOUND. DB exit_log: net rổ thực tế −2.13/−2.25/−3.20/−3.74/−3.91/−3.99/−4.49/−5.75 → **0/9 rổ** từng đạt ≥−1.50 → floor chưa bao giờ fire ✓ |
| **O1-Pro** | Đưa breaker PSL −$6.48 lên **đầu hàm** (bao phủ NAKED/LOCKED/UNWOUND) + floor BASKET_TIME → −$6.48 + rút `HEDGE_TIMEOUT_MIN` 30→**12-15′ cho rổ wall=None** | ✅ **ĐÚNG HƯỚNG, 1 nuance** | PSL hiện chỉ ở nhánh UNWOUND (L827) ✓ Red Team đúng. Nuance: với rổ LOCKED frozen (net −2.13…−4.49), breaker −6.48 **vẫn gần như dead** (chỉ fire khi slippage khóa cực đoan gap≥3.24pts) — **phần có tác dụng thật là floor BASKET_TIME −6.48 (mọi net frozen đều qua floor → đóng đúng lúc timeout) + timeout ngắn cho rổ không có cản** (rổ wall=None chỉ có 2 đường thoát: span 4.5pts — trong sideway hẹp có thể không tới — hoặc BASKET_TIME) |
| **F3** | Poll blocking 2-3s là **không cần thiết + có hại** (bão 6 lỗi RPC @03:20 → treo tick 18s → last_px trễ → tái phát Invalid-stops). RECOVER hiện có đã tự hồi (4876010029). Lỗ hổng thật chỉ là **chưa backfill entry_log** | ✅ **ĐÚNG** | 4876010029: **không có row entry_log** (DB) nhưng CÓ exit_log (HEDGE_TAKE leg +3.05 @02:04 → PRUNE −8.80 @02:05:56) = đã được RECOVER + chạy đúng trong máy rổ ✓. 03:20: 6 "no response" → 2 lệnh fill (4876206483/0502) **đều có entry_log + EXIT_SYNC** → không có orphan ✓. F2 phụ thuộc `last_px` tick-tươi → blocking poll = tự tái tạo điều kiện lỗi ✓ |
| **M1** | Đứt liên kết rổ sau stream-stall 02:25 → 4 rổ thả nổi → 8 lệnh đóng rời rạc (+$32.93/−$35.55) | ✅ **ĐÚNG + đã tìm root-cause** | Log 02:50:13 `adopt 8 positions` → **KHÔNG có dòng `[HEDGE] re-attach`** (so boot 01:40:03 có "re-attach 4 position (registry 2 rổ)") → registry RAM trống lúc boot → 8 vị thế bị máy EXIT xử lý **đơn lẻ** (TP +16.5pts / PSL −17.6pts, 8 close cùng tick 02:50:36-41) ✓. **Root-cause (code)**: `decide()` L1080-1084 `del self.hedge_baskets[k]` khi root vắng khỏi open_pos — **không phân biệt "root đã đóng thật" vs "root vô hình do RPC stall"** → registry bị wipe trong 02:25-02:49 → snapshot 02:49:27 ghi registry rỗng → boot 02:50 restore rỗng ✓✓ (chuỗi nhân quả khép kín) |
| **M2** | `day$` reset 0 trên RAM mỗi restart → **vô hiệu hóa cầu chì Daily-halt ($30)** | ✅ **ĐÚNG** | `scalp_executor.py` L23 `self.day_loss = 0.0` (chỉ RAM) · L280-281 `at_daily_cap = day_loss ≤ −30` · **không có dòng restore từ SQLite** (grep: không tồn tại). Log: 01:40:16 day$ **+3.72→+0.00** ngay sau restart F2 · 02:50:33 +0.00 · 05:01 +0.00 ✓. Hệ quả: ngày lỗ $28 + 2 lần cloud-flap = fuse chưa bao giờ chạm $30 (mất 2×$28 riêng rẽ) |
| **M3** | Lọt lưới chống bắn chùm ở R1R2: 4 lệnh MUA trong 30s, span chỉ 0.24pts | ✅ **ĐÚNG + đã tìm cơ chế** | Log 01:41:05-08: fills 4092.564/4092.601/4092.803/4092.766 (span **0.24pts trong 3s** + lệnh thứ 5 @01:41:32) — gate `_can_open_new_root` L683-689 so với **open_pos của tick trước** (4 lệnh arm fill cùng 1 `decide()`, cả 4 cùng vượt gate vì lệnh mới chưa vào list) → **bypass in-tick** (gate 0.35pts/5s chỉ chặn được cross-tick). 03:20: 8 arm → 2 fill sát nhau 4100.06/4100.073 ✓ cùng lớp |

**Phủ nhận/nhấn (chỉ 1 điểm, bằng số liệu):** Red Team nói "0/9 rổ cứu thành công" — chính xác cho **exit có lãi** (0 row BASKET_TP/UNWIND_BREAKEVEN/BASKET_TIME trong exit_log 15/10 ✓), nhưng rổ #2 **đã bank HEDGE_TAKE +$3.05** (1/9) — credit giảm lỗ root từ −$8.80 → net −$5.75. Chi phí hedge đúng = −$31.97 (TB −$3.55/rổ) như Red Team nêu ✓.

---

## §2. PHẢN BIỆN CHIẾN LƯỢC (A vs B) — phân tích first-principles

### 2.1. Số liệu kiểm định claim "hedge = bảo hiểm lỗ"
| Metric | 15/10 live (tick thật) | So sánh Red Team |
|---|---|---|
| Rổ lãi (BASKET_TP/UNWIND_BREAKEVEN) | **0/9** | ✓ đúng |
| HEDGE_TAKE banked | 1/9 (+$3.05, rổ #2) | nuance đã ghi §1 |
| Tổng chi phí hedge | **−$31.97** (−$3.55/rổ) | ✓ đúng |
| Lãi lệnh đơn (TP+SYNC) | **+$78…+$90.7** (36 lệnh, TB +$3.1) | ✓ đúng |
| Net ngày | **dương** (≈ +$46…+$59 closed) | hedge KHÔNG phá ngày, nhưng cũng KHÔNG đóng góp lãi thuần |
| Cắt thẳng −1.2pts (phương án A) | chi phí = 1.2×$2 + 1 spread ≈ **−$2.40…−$2.80**, slot free 0s, 0 rủi ro đứt liên kết | **rẻ hơn −$3.55/rổ live** ✓ (Red Team đúng trên ngày này) |

### 2.2. Phân rã giá trị của hedge 1:1 (first-principles)
- **Hedge KHÔNG tạo giá trị trung bình** (net frozen −gap×$2, bất biến theo giá — đã chứng minh §1). Giá trị duy nhất = **asymmetry**: (i) bắt được wall-bounce (HEDGE_TAKE — 1/9 live), (ii) rổ UNWOUND có thể lãi (BASKET_TP — 0/9 live, chưa từng).
- Chi phí cố định mỗi rổ: **1 spread + 1 slippage leg (≈$0.40-0.80) + giam 2 slot 34-142′ + tail rủi ro M1 (đứt link → PSL đơn −$35.55 = 44% tài khoản $81)**.
- **KẾT LUẬN KỸ THUẬT**: trên dữ liệu 15/10, hedge là chi phí dương (−$3.55/rổ) với upside chưa từng kích hoạt (0 BASKET_TP). Red Team đúng: **nếu mục tiêu = tối đa PnL, A thắng**.
- **NHƯNG**: quyết định LIVE hedge-ON là **D2-override của HUMAN** ("backtest offline không bao giờ chuẩn xác vì nến đã được làm mềm") — tức HUMAN chấp nhận chi phí hedge để giữ *opportunity* wall-bounce trong điều kiện tick-thật chưa đo đủ. A = **đảo ngược D2** → phải là quyết định của HUMAN, không phải của plan.

### 2.3. Đề xuất của tôi
| Phương án | Khi nào chọn | Rủi ro |
|---|---|---|
| **B (khuyến nghị kỹ thuật)** | HUMAN **giữ D2** (thí nghiệm hedge thêm, vá 5 lỗ hổng thật) | Pin test sẽ cần re-baseline (F1-Dir đổi hành vi PRUNE) · chi phí hedge tiếp tục (nhưng có trần: O1-Pro + M1/M2/M3 loại tail) |
| **A (clean, tối đa PnL)** | HUMAN muốn **chấm thí nghiệm hedge** (lắng nghe dữ liệu live + replay K=8) | Mã hedge thành dead code (để lại không chạy) · mất upside wall-bounce · cần gate replay cấu hình mới (KHÔNG so trực tiếp được với Gate-3 A do khác K cap) |

**Dù A hay B, 3 vá M1/M2/M3 + O1-Pro vẫn BẮT BUỘC** (M1/M2 = tail rủi ro tài khoản, không phụ thuộc hedge) — chỉ khác: A thì M1 thành "không-cần" (không còn rổ) nhưng M2/M3/O1-Pro-PSL (chống tail lệnh đơn) giữ nguyên, F1-Directional thành dead code bỏ qua.

---

## §3. WORKPLAN — Phương án B (default; không code trong file này)

> Quy trình mỗi cycle (đã chứng minh ở F2, ~15-30′ + gate): `worktree edit → py_compile → test_offline (dual-pin; re-baseline CHỈ khi HUMAN duyệt) → test_s2 9/9 → _replay_hedge.py (3 criteria) → verifier G4 (read-only) → HUMAN duyệt merge → ff-main → push → restart bot clean (adopt) → verify boot-log + status.json`. **Tất cả code chạy từ main; bot LIVE không được đụng runtime root** (zero-downtime rule).

### WS-1 · M2 — Khôi phục fuse day$ (an toàn độc lập, ưu tiên chạy TRƯỚC vì 0 rủi ro đổi hành vi entry)
| Mục | Giá trị |
|---|---|
| Sửa gì | `scalp_executor.py`: tại `adopt()`/boot, `day_loss` = `SELECT COALESCE(SUM(pnl),0) FROM exit_log WHERE ts ≥ start_trading_day_UTC` (start = 00:00Z của UTC day hiện tại — khớp windows (0, 1305)); `at_daily_cap` tính lại; dòng log `[BOOT] day$ restored +X.XX (N deals)` |
| Vị trí chính xác | executor L23 (init 0.0) → thay bằng restore-sau-adopt · L280 (at_daily_cap giữ nguyên) · main.py L328 (đã gọi `at_daily_cap` → tự hiệu lực) |
| Cấm | Không đổi ngưỡng $30 · không đổi cách tính day-rollover (L276) |
| Acceptance | Unit-test: DB fixture 2 ngày → restore đúng ngày hiện tại; boot log có dòng restored; simulate `day_loss=−25 + restart` → fuse vẫn còn −25 (trước fix: 0) |
| Tác động hành vi | **0 thay đổi entry** (chỉ chặt thêm trường hợp đã lỗ ≥$30 — đúng chức năng fuse) |

### WS-2 · M1 — Bảo toàn + khôi phục liên kết rổ (khóa chặt tail −$35.55)
| Mục | Giá trị |
|---|---|
| Sửa gì (3 điểm) | (1) **Prune-guard** `decide()` L1080-1084: chỉ `del` registry khi root **xác nhận đóng** (có exit row trong tick đó / broker deal-close) — root "vô hình do stall" (stall-flag: không tick > Ns / positions-poll fail) → GIỮ registry + giữ snapshot (2) **Exact-relink**: `enter()` (executor L24) ghi comment broker = `SCALP5-HEDGE:<root_id>` cho leg (root giữ `SCALP5`) → `adopt()` đọc comment → ghép parent_id CHÍNHCHECK (không heuristic); vị thế cũ (comment chưa có id) → fallback: cặp ngược-chiều + `tp is None` + entry-ts gần nhất (H: chỉ dùng 1 lần, sau đó comment mới luôn) (3) **Snapshot-guard**: không ghi snapshot registry rỗng khi có positions-hedge còn sống (chống chuỗi wipe 02:25→02:49) |
| Cấm | Không đổi logic exit rổ · không auto-close vị thế ở bước này |
| Acceptance | Unit-test: (a) simulate stall-adopt → registry restore đúng cặp (b) root-đóng-thật → prune đúng (c) snapshot không bao giờ rỗng khi có rổ mở · Replay: không đổi pin (M1 chỉ chạy sau-adopt) · Live: sự kiện stall kế tiếp → log `[HEDGE] re-attach ... (exact relink from comment)` + KHÔNG có mass-exit rời rạc |
| Tác động hành vi | Chỉ ảnh hưởng đường sau-restart (hiện = 8 lệnh cùng tick 02:50) |

### WS-3 · O1-Pro — Cầu chì rổ + giải phóng slot (chỉnh lại O1 gốc theo Red Team)
| Mục | Giá trị |
|---|---|
| Sửa gì | (1) `config.py`: +`PSL_BASKET_USD = 6.48` · `BASKET_TIME_MAX_LOSS_USD = 6.48` (thay 1.50) · +`HEDGE_TIMEOUT_NOWALL_MIN = 15` (thay 30 cho rổ wall=None) (2) `scalp_strategy.py` L716+: **breaker net ≤ −PSL_BASKET_USD đặt ĐẦU hàm** (trước cả NAKED check) — bao phủ mọi trạng thái (NAKED: root trần âm sâu · LOCKED: frozen gap bất thường · UNWOUND: giữ hiện trạng L827 nhưng thống nhất đọc config mới) (3) L810: điều kiện `wall_px is None` → timeout dùng `HEDGE_TIMEOUT_NOWALL_MIN` (4) floor L812/L837 đọc config mới |
| Cấm | Không đổi trigger HEDGE_LOCK_PTS (1.2) · không đổi HEDGE_TAKE · không đổi PSL vị thế đơn (3.0pts) |
| Acceptance | test_offline pin: hedge-ON (baseline 82 → **sẽ đổi** vì rổ đóng sớm hơn giải slot; HUMAN duyệt giá mới) + hedge-OFF pin 493 (không đổi — O1 chỉ chạm máy rổ) · Replay: worst_basket ≤ −6.48 ✓ · KPI slot-time: rổ LOCKED wall=None ≤ 15′ (hiện: tới 142′) · rổ frozen không giữ slot > timeout |
| Tác động hành vi | Rổ đóng sớm hơn (net frozen không đổi) → tăng số entry khả dụng (đánh giá qua pin + replay) |

### WS-4 · F1-Directional — Chữa PRUNE-INSTANT đúng (thay bản F1 cũ — F1 cũ CẤM dùng)
| Mục | Giá trị |
|---|---|
| Sửa gì | `scalp_strategy.py` `_find_structural_wall` L692-714: (1) +`HEDGE_WALL_PAD_PTS = 0.3` (config) (2) L-root: bộ lọc `w <= px − pad` rồi lấy **max** (cản gần dưới px nhất) (3) S-root: `w >= px + pad` rồi lấy **min** (4) bộ rỗng → `None` (nhánh PRUNE_SPAN/BASKET_TIME hiện có L782/L810 xử lý — không đổi) (5) L751-753 & L769-771 (2 call-site re-search) tự hưởng thụ sửa vì cùng hàm |
| Cấm | **KHÔNG** dùng `abs(w−entry)` (đã chứng minh sai §1) · không đổi HEDGE_BREAK_PTS (1.0) |
| Acceptance | test_offline pin hedge-ON: **chờ đo** (giả thuyết: ≤82 — rổ sống lâu hơn → slot bận lâu hơn → entries ít hơn; HUMAN duyệt re-baseline nếu khác) · test_s2 9/9 · Replay: PRUNE-INSTANT (branch=LOCKED, age<10s) = **0** (baseline 15/10: có, 82→122 artifact của bản F1 cũ) · KPI live: 0 rổ bị PRUNE trong 10s đầu LOCKED |
| Tác động hành vi | TRỪ khi có cản vô lý giữa px-entry — thay đổi hành vi rổ (chính là mục đích) |

### WS-5 · M3 — Chống bắn chùm R1R2 (gate lúc EXECUTE, không phải lúc ARM)
| Mục | Giá trị |
|---|---|
| Sửa gì | (1) `scalp_strategy.py`: +hàm hủy arm: trước mỗi `ENTER` arm-fill, gọi lại `_can_open_new_root` với `open_pos` + các fill **cùng tick đã khớp** (pass list fill-đã-giải-quyết của main) (2) sau mỗi fill root thành công, **hủy mọi R-arm cùng chiều có `abs(arm.px − fill_px) < 0.35`** (arm pending trong `r1r2_arms` L79; giữ arm cách ≥0.35pts) (3) main.py L587-594: truyền danh sách "fill trong tick này" vào decide/execute (1 tham số) |
| Cấm | Không đổi ngưỡng 0.35/5s · không chặn v0-MOM1 (v0 có re-fire ≤2/nến riêng — chỉ áp cho R1R2 burst như evidence 01:41/03:20) |
| Acceptance | Unit-test: 5 arm cùng chiều cách 0.24pts → **≤1-2 fill** (hiện: 4) · pin test: số entry có thể giảm (loại burst thừa) → HUMAN duyệt giá pin mới · Live: 0 cặp fill cùng chiều Δpx<0.35 & Δt<5s |
| Tác động hành vi | Giảm burst (01:41: 4 fill→1-2) — có thể giảm volume; PnL/lệnh đơn vẫn +3.1 TB |

### WS-6 · F3-audit (P3, optional, không blocking)
| Mục | Giá trị |
|---|---|
| Sửa gì | Khi RPC "no response": KHÔNG sleep blocking (cấm theo Red Team ✓). Thay: (1) đánh dấu attempt `missed-rpc` (2) khi position-poll RECOVER phát hiện vị thế mới (magic match, chưa có entry row) → **backfill row `entry_log` (kind=RECOVER, ts=entry thực)** — chỉ việc ghi DB audit, 0 tác động tick loop |
| Acceptance | DB: số row RECOVER = số vị thế recover mà không có entry row (baseline 15/10: 1 = 4876010029) |

### Thứ tự thực thi (dependency + rủi ro)
```
WS-1 (M2, độc lập, 0 đổi hành vi) ──► cycle 1   │ an toàn nhất, chạy trước
WS-2 (M1, độc lập, chỉ đường sau-restart) ──► cycle 2 │ (1)(2)(3) cùng commit, 1 cycle
WS-3 (O1-Pro, đổi pin rổ) + WS-4 (F1-Dir, đổi pin rổ) ──► cycle 3 │ CÙNG 1 file máy rổ + cùng 1 lần re-baseline
WS-5 (M3, đổi pin entry) ──► cycle 4 │ sau cycle 3 (vùng gate overlap, tránh 2 biến cùng pin)
WS-6 (F3-audit, optional) ──► gộp vào cycle bất kỳ
```
**Mỗi cycle dừng tại "HUMAN duyệt merge"** (zero-downtime rule) · tổng 4 cycles ≈ 1.5-2h máy + gate.

---

## §4. WORKPLAN — Phương án A (nếu HUMAN đảo D2: loại hedge, tối đa PnL)

| Bước | Nội dung | Gate |
|---|---|---|
| A1 | `HEDGE_ENABLE=False` (config flip — máy rổ thành dead path, code giữ nguyên không xóa) | test_offline pin = **gate-2 baseline hedge-OFF = 493** (đã có sẵn, KHÔNG cần re-baseline) |
| A2 | **HARD-CUT module**: root âm chạm `HARD_CUT_PTS=1.2` (config mới) → `EXIT root` (thay bước mở leg); +cooldown `HARD_CUT_COOLDOWN_SEC=60` cho hướng đó (chống re-enter lập tức) | test_s2 9/9 · unit: 1 lệnh đơn, 1 spread, slot free 0s |
| A3 (optional) | Tách HEDGE_TAKE thành tín hiệu R1R2 chuẩn: zone L chạm + bounce → lệnh gốc MUA TP 1.5pts (không gắn vào lệnh gốc đang lỗ) | pin riêng · replay |
| A4 | **Replay cấu hình MỚI** (KHÔNG so số với Gate-3 A vì khác K/hard-cut): 12-ngày, K_CONTEXT=8 + hedge-OFF + hard-cut → metric: entries, PnL, worst-trade, slot-time | 3-criteria + HUMAN duyệt số trước merge |
| A5 | Merge + push + restart (adopt 0 — không có rổ nào nữa) | boot-log + LIVE START + 0 `[HEDGE]` lines |

**Chi phí thực thi A**: ~30%工作量 B (A1+A2, bỏ WS-3/4/5-parte-rổ) — **NHƯNG vẫn phải chạy WS-1 (M2) + WS-2 (M1-lite: không còn rổ → chỉ còn M2 fuse) + WS-5 (M3)** — vì 3 lỗ hổng này độc lập với hedge.

---

## §5. BẢNG CHẤP NHẬN TỔNG (KPI before/after, đo bằng log/DB)
| KPI | Trước (evidence 15/10) | Sau B (target) | Phương pháp đo |
|---|---|---|---|
| Rổ PRUNE-INSTANT (<10s sau lock) | 1 (−$2.52) + pin artifact | **0** | exit_log: `PRUNE_BREAK branch=LOCKED` với ts−lock_ts<10s |
| Rổ giữ slot không đường thoát | 142′ (rổ #3/#4) | **≤15′ (wall=None) / 30′ (wall valid)** | exit_log ts−lock_ts theo trạng thái wall |
| Worst rổ (live) | −$5.75 (replay −$10.36) | **≤ −$6.48** | exit_log Σ net/rổ |
| day$ fuse sau restart | bị reset 0 (01:40, 02:50, 05:01) | **restore từ DB** | log `[BOOT] day$ restored` + test simulate |
| Mass-exit rời rạc sau stall | 8 lệnh cùng tick (02:50:33) | **0** (rổ restore exact, exit theo máy rổ) | exit_log cùng-ts >2 lệnh |
| Fill chùm cùng chiều | 4 fills/3s/0.24pts (01:41) | **≤1-2** | entry_log Δpx/Δt |
| "Invalid stops" | 0 (post-F2) | **0** (giữ nguyên — F2 không đụng) | log grep |
| Entry orphan (no-response) | 1 (4876010029, audit thiếu) | row RECOVER có đủ entry_log | entry_log count |

---

## §6. GIỚI HẠN CỦA FILE NÀY & RỦI RO CÒN LẠI
- Plan này **chưa chạy test/replay** (đúng lệnh "viết plan không code") — mọi số "sẽ đổi pin" là **dự báo cần xác nhận bằng gate cycle 3**.
- Rủi ro provider (MetaApi flapping, 6+ episode/ngày) **không được vá bởi bất kỳ WS nào** — M1/M2 chỉ giảm thiệt hại; root-cause nằm phía cloud (ticket support vẫn open theo docs).
- **Quyết định thuộc về HUMAN**: (i) A hay B (ii) duyệt re-baseline pin (iii) duyệt merge từng cycle. Agent KHÔNG tự chuyển state nào trong 3 điểm này.

## PHỤ LỤC — Tái tạo bằng chứng
```bash
cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
sqlite3 "file:data/scalp5.db?mode=ro" "SELECT datetime(ts,'unixepoch','+7 hours'),reason,pnl FROM exit_log WHERE ts>1791993000;" 
grep -nE "re-attach|adopt" logs/scalp5.out | awk -F'2026-10-15 ' '{split($2,a,","); if (a[1]>="02:45:00"&&a[1]<="02:55:00") print}'
grep -n "del self.hedge_baskets\|BASKET_TIME_MAX_LOSS\|DAILY_LOSS_STOP" src/scalp_strategy.py src/scalp_executor.py src/config.py
```
File: `docs/REVIEW-REDTEAM-1510-PLAN.md` · v1.0 (15/10 06:3x+07) · chưa code (theo lệnh HUMAN).
