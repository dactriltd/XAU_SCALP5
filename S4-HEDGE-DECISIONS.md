# S4-HEDGE — CÁC PHƯƠNG ÁN CẦN LẤY Ý KIẾN

> File này là **bản tóm lược duy nhất** cần anh/chị chốt ý. Ngày: 15/10/2026.
> Nhánh `s4-hedge` (commit `c765899`) đã code xong + chạy hết gate. Chưa merge, chưa flip flag.
> Bot live PID 7710 chạy nguyên gạc (zero-downtime, không touch runtime root).

## 1. Bối cảnh (kết quả các gate)

| Gate | Kết quả | Evidence |
|------|---------|----------|
| G1 (py_compile 6 files) | ✅ PASS | — |
| G2 (regression, `HEDGE_ENABLE=False`) | ✅ PASS | `test_offline` ALL PASS (pin 471) · `test_s2` 9/9 · state round-trip OK → **parity 100%** |
| G3 (replay adversarial 12 ngày) | ❌ **FAIL 0/3** | `logs/replay_hedge.txt`: PnL A +$6,985.97 vs B +$217.66 · worst_basket −$7.05 (trần −$6.48) · 37/42 PRUNE outliers −$3.36±$0.10 · volume 238 vs 4,886 entries |
| G4 (verifier) | ⏳ đang chạy | → `logs/verifier_s4_hedge.txt` (kết quả sẽ bổ sung) |

**Chẩn đoán gốc** (plan §7.5): orchestrator cap roots = 2 → hedge "tắt" volume (238 vs 4,886 entries).
Do G3 FAIL → theo quy tắc D2, **giữ `HEDGE_ENABLE=False`**, chưa flip, chưa merge.

## 2. Ba phương án chính (S4-HEDGE)

### 🔷 P1 — Merge "subset an-toàn", hedge DORMANT (khuyến nghị)
- Merge CHỈ phần an-toàn-hóa: fix F1 EXIT_SYNC (deal-history → fallback +$2.52) + tlog/telegram leg-ready (tp=NULL). Toàn bộ hedge logic nằm **sau flag `HEDGE_ENABLE=False`** → merge KHÔNG đổi hành vi bot live (Gate 2 đã chứng minh parity 100% khi off).
- Lợi: rủi ro live = 0 · code sẵn sàng để bật khi đủ điều kiện · F1 fix luôn có hiệu lực.
- Trừ: S4-hedge chưa được "mở" (chờ P2 hoặc điều kiện replay tốt hơn).

### 🔷 P2 — Tune lại orchestrator + re-gate
- Nới `MAX_ROOT_POSITIONS` (2 → 4/∞) + giảm `MIN_ROOT_GAP_SEC` · giữ hedge LOCK (đo riêng "chỉ hedge, không bóp volume") · chạy lại `_replay_hedge.py` (cập nhật theo tham số mới).
- Lợi: có cơ hội Gate 3 PASS thật → flip flag được.
- Trừ: +1 cycle (replay + verifier) · có thể vẫn FAIL vì volume là vấn đề gốc · đổi 2 tham số cùng lúc → cần tách biến (đo riêng từng tham số).

### 🔷 P3 — Giữ branch, đóng S4-HEDGE
- Chỉ giữ commit + bằng chứng trên GitHub; S4 chuyển BACKLOG (ghi STATE.md). An toàn nhất.
- Trừ: S4 không được triển khai trong giai đoạn này.

## 3. Các câu hỏi cần anh/chị chốt

- **Q1 (bắt buộc)**: Chọn **P1 / P2 / P3**? (khuyến nghị P1)
- **Q2 (nếu P1)**: Timing merge — (a) ngay sau khi G4 = APPROVE, hay (b) đợi boundary ROL 21:45Z / bot flat? (Merge chỉ đổi source tree; bot 7710 giữ code trong memory đến khi restart → (a) an toàn về mặt hành vi live; (b) là cách "sạch" nhất cho 4-line cutover sau này.)
- **Q3**: Nếu G4 = REJECT → cho phép 1 cycle fix (theo loop-constraints: max 3 lần/item) rồi re-verify? (mặc định = CÓ, nhưng xin xác nhận)
- **Q4**: Giữ branch `s4-hedge` trên GitHub (repo private) làm bằng chứng + sẵn sàng bật flag sau này, hay xóa sau khi merge/P3?

## 4. Ghi chú backlog (chưa cần quyết định ngay)

- CLOSE-FAIL retry cap 2 · Reference-TF backfill 1h/4h/D1 · rolling-5m reference tag · S3-C tuning sweep (trục in-flow-confirm / STALL_M1 / K_CONTEXT / G2LVL_PTS) — tất cả đã ghi STATE.md, chờ sau S4.

## 5. Bằng chứng kèm (đường dẫn)

- `docs/S4-HEDGE-plan.md` §7 (evidence + chẩn đoán) · §8 (P1/P2/P3 chi tiết)
- `logs/replay_hedge.txt` (Gate 3 số liệu đầy đủ)
- `logs/verifier_s4_hedge.txt` (Gate 4, đang chạy)
- `STATE.md` (L2 approval + whitelist/denylist + run log)

> **Quy tắc ghi nhận**: mọi merge/push đều cần anh/chị duyệt; flip `HEDGE_ENABLE=True` CHỈ sau khi đủ 3 tiêu chí Gate 3 PASS + re-run test (D2).
