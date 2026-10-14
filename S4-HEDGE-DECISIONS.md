# S4-HEDGE — CÁC PHƯƠNG ÁN CẦN LẤY Ý KIẾN (v2 · sau P2-Tuned)

> Bản cập nhật 15/10 00:5x+07. Anh/chị đã duyệt P2-Tuned (Q1–Q4) → tôi đã thực hiện 1 cycle.
> **Kết quả: GATE 3 FAIL 0/3 (lần 2) → KHÔNG merge, KHÔNG restart, KHÔNG flip flag (D2).**
> Bot live PID 7710 chạy nguyên gạc, không bị đụng.

## 1. Điều đã làm (P2-Tuned, đúng chỉ thị)

| Hạng mục | Trạng thái |
|---|---|
| `K_CONTEXT` 4→8 · `MAX_ROOT_POSITIONS` 2→4 · `MIN_ROOT_STEP_PTS` 0.35 · `MIN_ROOT_GAP_SEC` 5s · `HEDGE_TIMEOUT_MIN` 30 · `BASKET_TIME_MAX_LOSS_USD` 1.50 · `BASKET_TP_TRIGGER_USD` 1.20 | ✅ trong branch |
| Per-position hedge (gỡ khóa toàn cục + bỏ điều kiện +0.5pts) | ✅ trong branch |
| `BASKET_TIME` (LOCKED+UNWOUND, 30′, net ≥ −$1.50) + `UNWIND_BREAKEVEN_GUARD` (peak ≥ +$1.20 rồi ≤ +$0.50 → chốt) | ✅ trong branch |
| G1 py_compile | ✅ PASS |
| G2 (hedge-ON: test_offline pin=82, v0-signal 0/58, test_s2 9/9, state-rt) + G2 (hedge-OFF K=8: pin=493) | ✅ PASS |
| **G3 replay 12 ngày** | ❌ **FAIL 0/3** (evidence §2) |
| G4 verifier (commit P2-Tuned) | ⏭️ chưa chạy — điều kiện LIVE yêu cầu G3 PASS trước; bằng chứng G3 FAIL đã đủ |
| Merge/restart/flip | ❌ không (chưa đạt điều kiện) |

## 2. Bằng chứng GATE 3 lần 2 (`logs/replay_hedge.txt`)

| Tiêu chí | Trần | Kết quả | |
|---|---|---|---|
| 1. worst_basket | ≥ −$6.48 | **−$10.36** | ❌ |
| 2. PRUNE_BREAK(LOCKED) ≈ −$3.36±0.10 | 100% rổ trong tolerance | **184/201 outliers** (mẫu: −6.02, −4.11, −6.21…) | ❌ |
| 3. PnL 12d B ≥ A | A = +$6,985.97 (V2, K=4 pin) | **B = +$561.07** (diff −$6,424.90) | ❌ |

Volume B đã lên (238 → **1,104 entries**) nhưng PnL/vụ hedge âm: **402 PRUNE_BREAK vs chỉ 39 HEDGE_TAKE**.

### Chẩn đoán (evidence, không phỏng đoán)
1. **Tail −$10.36: NAKED/LOCKED không có PSL breaker.** Cầu chì −$6.48 chỉ có ở nhánh UNWOUND; rổ đang khóa (LOCKED) lỗ sâu thì KHÔNG có trần — phải chờ phá cản (m1-proxy tick overshoot lớn) hoặc PRUNE_SPAN. → Bug thiết kế cần vá.
2. **BASKET_TIME floor −$1.50 ngược chiều**: rổ LỖ SÂU (< −$1.50) không được release → chôn thêm 30′ rồi cắt lỗ sâu hơn.
3. **PnL gap = volume suppress**: 1,104 vs 4,886 entries; hedge hold slot trung bình cả phiên → bot "ngồi im" nhiều hơn so với V2 thuần.
4. Note: tiêu chí 1/2 còn bị m1-proxy δ-overshoot khuếch đại (tick live 0.01–0.1pt sẽ nhẹ hơn — đã ghi §7.5) nhưng tiêu chí 3 (PnL B < A) là FAIL thật.

## 3. Ba phương án (chọn 1)

### 🔷 O1 — Vá tail-risk + re-gate (khuyến nghị nếu muốn LIVE hedge thật)
- ~6 dòng: thêm PSL breaker vào nhánh LOCKED (net rổ ≤ −$6.48 → đóng cả rổ, reason `PSL`) + hạ BASKET_TIME floor xuống −$6.48 (release slot kể cả rổ lỗ sâu).
- Chạy lại G3 (cycle 2 — Q3 chỉ duyệt 1 cycle, cần anh/chị duyệt thêm).
- Rủi ro: gate-1/2 vẫn có thể FAIL do m1-proxy overshoot (artifacts đã ghi) → khi đó phải dùng replay tick-level (data chưa có) hoặc chấp nhận tiêu chí 1/2 với giả định proxy + chỉ gate-cứng là #3 (PnL B ≥ A) — **cần anh/chị duyệt chuẩn này trước**.

### 🔷 O2 — Merge "volume-only" (hedge dormant): K_CONTEXT=4→8 ship ngay
- Chỉ merge thay đổi an-toàn: K_CONTEXT=8 + P1 (F1 EXIT_SYNC, tlog/tg leg-ready, hedge dormant sau flag) → live = V2 mở rộng trần lệnh (test: 493 vs 471 entries, +4.7%, exit-mix lành, K-gate ✓, zero hedge risk).
- Re-gate nhanh: chạy lại `_replay_v2.py` (gate §14.3) với K=8 trước merge (read-only, ~1 phút).
- LIVE restart tại boundary theo Q2 (user đã chọn "ngay lập tức" — với O2 = sau re-gate K=8 PASS).

### 🔷 O3 — Giữ branch parked, S4 → BACKLOG
- Trạng thái hiện tại: P2-Tuned staged, flag OFF, bằng chứng đủ. Đợi cycle sau (vd: data tick-level, hoặc thiết kế lại hedge entry-timing/lock-ttl ngắn hơn).

> O4 (chạy LIVE hedge-ON ngay, bỏ qua G3 FAIL) = **vi phạm D2 + verdict gate — không khuyến nghị.**

## 4. Các câu hỏi cần chốt

- **Q5 (bắt buộc)**: Chọn **O1 / O2 / O3**?
- **Q6 (nếu O1)**: Duyệt cycle 2? + duyệt "chuẩn gate khi proxy overshoot": gate-cứng = #3 (PnL B≥A) còn #1/#2 ghi nhận artifact proxy (vd: worst_basket chỉ cần ≥ −$6.48 + 1 tick-overshoot, PRUNE-lock tolerance nới theo m1-proxy)?
- **Q7 (nếu O2)**: Chạy re-gate K=8 rồi merge + restart ngay (đúng Q2 cũ) hay dời sang boundary ROL?

## 5. Ghi chú phụ

- Branch `s4-hedge` trên GitHub = bản P2-Tuned (commit parking sẽ cập nhật).
- Backlog không đổi (CLOSE-FAIL cap 2 · ref-TF backfill · rolling-5m tag · S3-C sweep).
