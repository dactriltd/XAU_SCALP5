# P2-H3 RESEARCH PLAN — IMPULSE SPAN CAP ("C8: Mua đuổi đỉnh sóng") · NGHIÊN CỨU CHUYÊN SÂU
> 15/10 10:4x+07 · BẢN GỐC: L1 PLAN-ONLY → CẬP NHẬT 11:0x (§0.1): HUMAN PHÊ DUYỆT C8-Unified — code+unit-test chuẩn bị trong worktree s4-hedge; bot 97539 VẪN CHẠY ĐẾN ROL 21:45Z (hoặc lệnh HUMAN khi open=0, merge+restart 1 lần duy nhất)
> Áp dụng bộ luật AGENTS.md (Karpathy): First Principles · Minimal Abstractions · Empirical · Baseline-First · Pedagogical
> Dữ liệu: `data/scalp5.db` (entry_log/exit_log/regime_log, đọc chế độ RO) · `logs/2026-10-15_scalp5.log` · `logs/scalp5_timeline_1510.csv`
> Nguồn "nội dung áp dụng": phân tích Red Team C8 (HUMAN 10:0x) + live-anchor refinement (Agent 10:1x, STATE §10:1x)

---

## §0.1 CẬP NHẬT 11:0x — KIỂM ĐỊNH RED TEAM HUMAN (mọi số đã verify độc lập trên DB RO, không nhận theo copy)
**Verdict: 3/3 claim HUMAN ĐÚNG (với 2 rounding note) → tài liệu này đã đính chính §4/§5.1/§9 theo kết quả kiểm định:**
1. **Claim 1.1 (live-anchor tại mỗi giây) = VERIFIED 100%**: A1 09:18:27 & B1 09:56:00 & B2 09:57:01 = **0 lệnh L cùng chiều CÒN MỞ** (chùm trước đã TP/EXIT_SYNC từ 09:15:35–09:17:49 / 09:54:31–34) → O2 CHO QUA (giữ TP +3.94/+3.04/+2.99) · A2 span +0.436 qua · A3 **span +1.418 > 1.0 → G3 CHẶN (cứu rổ −2.93)** · B3 span −0.261 qua (TP +3.06). → **O2 thật = chặn 1/6 (chỉ A3), TP loss = $0, Δ +$2.93** — con số "−9.9$" trong bản gốc §4/§5.1/§9 là **LỖI STATIC-ANCHOR của Agent** (tính anchor từ entry đầu chùm như thể vẫn còn mở). Đã bỏ.
2. **Claim 1.2 (O3 dead code) = VERIFIED (theo đúng nghĩa cluster = open-NAKED + realized của chính nó)**: tại điểm G3 fire, mọi NAKED cùng chiều bên dưới đang dương (unrealized) → `net<0` không thể xảy ra đồng thời với G3 → O3 ⊂ O2 (hoặc trùng, hoặc chết) → **O3 LOẠI** (không còn giá trị độc lập vì O2 đã 0 TP-loss).
3. **Claim 1.3 (Case D −29.00 = POST-LEG 30s, không phải "ngoài phạm vi") = VERIFIED**: root 4877538554 mở 10:01:01 = **13s sau leg 4877535620 (10:00:48)** → G5 chặn → xóa ind −29.00/net −3.27. §2.4/§4.4 "không option nào chặn được" = **RETRACT** (sai vì chỉ xét span-cùng-chiều, bỏ sót thời điểm sau-leg).
- **Rounding notes (không đổi kết luận)**: B_0844 thực tế −2.74 (HUMAN −2.73) · B_1009 = −2.74 (HUMAN gán −3.35 = net của rổ B_1034 @10:34).
- **HƯỚNG DẪN MỚI CỦA HUMAN (áp dụng từ bản này)**: (i) **bỏ bước Replay-12d làm gate + không ép giữ pin 565** — chỉ gate bằng unit-test + KPI thực chiến · (ii) **PHÊ DUYỆT C8-Unified** (O2 + G1/G2/G4/G5) tại `_can_open_new_root` (L665) · (iii) code + unit test **chuẩn bị trong worktree `s4-hedge` ngay**, merge+restart **1 lần duy nhất tại ROL 21:45Z hoặc open=0** · bot 97539 GIỮ NGUYÊN tới lúc đó.

## §0 BẢNG MAPPING LUẬT → MỤC (đảm bảo mọi luật được áp dụng)
| Luật | Yêu cầu | Mục trong file này |
|---|---|---|
| L0 First Principles | bóc đến cơ chế | §2 (cơ chế entry/cơ học ΔE/phân rã lỗ/giới hạn cap) |
| L1 Minimal Abstraction | ≤15 dòng thuần, có chứng cứ | §4 (O2 = 6 dòng + 1 config; chứng minh minimality) |
| L2 System-2 | REPL/benchmark trước khẳng định | §5 (sanity check thiết kế sẵn, chưa chạy — L1 cấm code) |
| L3 Empirical Only | mọi claim kèm evidence | §3 (mỗi số gắn ts + pos_id + exit reason) |
| L4 Context=RAM | chỉ nạp tối thiểu | §3 là bảng KPI thay vì paste log thô |
| L5 CPU vs I/O | đọc DB/tool, không phỏng đoán | §3 = read-only DB query · §7 mới là I/O (code) |
| L6 Agentic Loop | Plan→Act→Observe→Reflect | §7 (S1-S6, mỗi step 1 ACT + 1 OBSERVE) |
| L7 Deconstruct | atomic blocks đầu task | §1 (B1-B5) |
| L8 Sanity Check | code kiểm chứng trước giải pháp | §5.1 (REPL tĩnh 6-event) |
| L9 Baseline & Benchmark | vanilla baseline + metric | §3.5 + §6 (baseline KPI + acceptance trước/sau) |
| L10 Pedagogical | analogy + sơ phạm | §8 |

---

## §1 DECONSTRUCT (LUẬT 7) — Bóc "mua đuổi đỉnh IMPULSE" thành khối nguyên tử
| Block | Input → Output | Bằng chứng (evidence) |
|---|---|---|
| **B1 — Cơ chế entry** | tick px + M0 → lệnh NAKED hay không | M0 gate `scalp_strategy.py:604` (`if self.m0_regime=="IMPULSE"` — **chỉ block ARM/LVL**). 6 tick-sites không bị block: `_can_open_new_root` L665, call-sites L962 (B_SNEO-L) · L977 (MOM1-L) · L988 (MOM1-S) · L1009 (B_SNEO-L2) · L1027 (B_SNEO-S2) · L1051 (R-arm). Evid live: cluster A 09:13–09:19 & cluster B 09:54–09:57 (IMPULSE/up speed 1.36/1.17, L-fire liên tiếp). |
| **B2 — Cơ học khoảng cách** | 2 NAKED cùng chiều → ΔE_entry < TP=1.5pts | `TP_POINTS=1.5` (config L17). Cluster A: L-muộn 4146.158 − L-đầu 4144.630 = **1.528 > 1.5** (lệnh 4 fire khi giá đã chạy hết biên độ TP của chùm — đúng công thức HUMAN). |
| **B3 — Phân rã lỗ leg** | rổ khóa → leg_loss | leg_loss_pts = `HEDGE_LOCK_PTS` 1.2 (config L136) + reversal = `HEDGE_RECOVERY_PTS` 1.0 (L153) + fill-slippage ~0.3 → **2.565pts = $5.13** (verify 4877283405: fill 4143.68 vs strategy-px 4143.867, exit 4146.245). Sai lầm attribution cũ: gán "slippage 1.365 = speed 1.36" — thực tế slippage chỉ ~13% con số; phần lớn = price-reversal (RECOVERY semantics P2-H). |
| **B4 — Giới hạn thiệt hại (net)** | rổ → cap | `PSL_BASKET_USD` −6.48 (L149, net rổ, mọi trạng thái) + BASKET_TIME 15-30′ (L143) + RECOVERY net cặp −2.5..−4.6. **Leg/rroot riêng lẻ** không cap → tail ind: −10.74 (09:25) · −10.31 (09:54) · **−29.00 (10:30:43, lớn nhất ngày)**. |
| **B5 — C8 = chặn B1 → giảm mẫu B3/B4** | M0==IMPULSE + span > threshold → chặn entry cùng chiều | ~6 dòng tại gate B1 (§4). Không sửa B3 (toán bất diệt của RECOVERY) mà **giảm tần suất tạo rổ**. |

---

## §2 FIRST PRINCIPLES (LUẬT 0) — Cơ chế hoạt động (mổ xẻ)
1. **M0 gate 2 lớp**: `L604` chặn ARM-LVL trong IMPULSE (đúng "không fade ngược sóng"); 6 tick-sites (B1) fire theo kinematics (MOM1/B_SNEO/R-arm) → **vào lệnh thuận sóng vẫn chạy trong IMPULSE** = nguồn "chase-buy". Đây là by-design ("VÀO LỆNH NHIỀU THEO DÒNG CHẢY", north-star 14/10) — C8 chỉ thêm **hàng rào chiều cao**, không tắt B1.
2. **Vật lý của chase**: sóng IMPULSE speed 1.17–1.36 pts/nến → 3-4 lệnh cùng chiều cách nhau 0.3–0.6pts (đủ > MIN_ROOT_STEP 0.35 L170 để được phép) nhưng lệnh thứ 4+ ở cách 1.0–1.5pts = **vào đúng vùng TP của lệnh đầu** (B2). Khi sóng "nhuộm" (reversal): các lệnh cao cùng ăn reversal cùng lúc → rổ.
3. **Toán lỗ leg bất diệt** (B3): một rổ RECOVERY net = root(+1.0×$2) + leg(−(1.2+1.0+slip)×$2) ≈ **−2.5..−3.5$/rổ** — là giá của fast-slot engine (giữ slot 1.3–3.0′ thay vì treo 15–30′). C8 không loại được B3 mà **giảm số rổ** (fewer legs opened) → giảm sum(B3).
4. **Tail ind vs net** (B4): evidence 10:30:43 HEDGE_TAKE_PAIR (root 4877538554 L@4161.534 10:01:01 → exit 4147.033 = −14.5pts = **−$29.00 ind** · leg 4877540882 S@4160.196 → +$25.73 · **net −$3.27 ≤ −6.48 cap ✓**): bản gốc ghi "CREEP-span 0.73pts (<1.0 → BẤT KỲ option nào cũng KHÔNG chặn được)" — **RETRACT (11:0x, verify §0.1-3)**: entry 10:01:01 mở **chỉ 13s sau leg HEDGE 4877535620 (10:00:48)** → **G5 POST_LEG_30S của C8-Unified CHẶN CHÍNH XÁC** → xóa ind −29.00/net −3.27. C8 đánh giá trên **net cluster + tần suất tail**, không phải cảm giác con số ind.

---

## §3 EMPIRICAL BASELINE (LUẬT 3, 9) — Số thật tính đến 10:36
### 3.1 KPI ngày (read-only DB, 10:36)
| Chỉ số | Giá trị | Evidence |
|---|---|---|
| Day PnL (exit_log SUM từ 07:00) | **+107.79$ (115 exits)** | khớp in-memory status.json day$=107.79 @10:35:04 ✓ |
| M2 cross-check (09:49:44) | 46.29 (PRE-P2H, 53 exits) + 36.99 (P2-H, 35 exits) = **83.28 ≈ 83.29 restore ✓** | tuyệt đối (±0.01 rounding) |
| IMPULSE episodes hôm nay | **16** (regime_log 07:06→10:35; up 8/down 8, speed 0.52–1.44) | query §3.2 |
| Chase-events (>1.0pt vs live-anchor NAKED, verify §0.1) | **6** (A:3 · B:3) — thực tế CHỈ 1 events vượt gate G3 (A3 +1.418) | bảng §4 |
| C7 CROSS_RESCUE | **★ 1 CẶP LIVE (10:50:39) = FIRE ĐẦU TIÊN**: pair L@4146.298 (10:48:42 → `CROSS_RESCUE_LOSER` −1.30$ @4145.777) + S@4146.912 (10:49:05 → `CROSS_RESCUE_WIN` +1.79$) = **net +0.49$ ≥ min +0.30 ✓ · KPI C7-PASS (70′ đầu sau restart, trước ROL)**. replay dự báo ~0.75 cặp/ngày ✓ | exit_log reason=`CROSS%` + log |
| Open positions | **0** @10:50:39 (sau cặp C7; slot sạch) | status.json |

### 3.2 Bảng cluster (chase-event = entry cách anchor-live > 1.0pts)
| Cluster | M0 (speed) | Entries | Chase-events | Kết quả | **Net** |
|---|---|---|---|---|---|
| A 09:13–09:19 (PRE-restart) | IMP/up 1.36 | L×6 (4144.630→4147.576) + S-leg | 3: 4146.158/4146.594/4147.576 | TP +2.84/+3.23/**+3.94**/**+3.07** · RECOVERY pair −3.07 · HEDGE_TAKE pair −2.93 (root ind −10.74) | **+7.08$** |
| B 09:54–09:57 (P2-H2) | IMP/up 1.17 | L×5 (4152.647→4159.103) | 3: 4156.865/4159.103/4158.842 | TP/EXIT_SYNC +3.04/+3.06/+2.99/+2.67 (TOÀN DƯƠNG) | **+3.05$** (gồm churn C) |
| C 10:01–10:02 (P2-H2, CREEP) | CR/up 0.91 | L×3 (4160.94→4161.67) + S | 0 (span 0.73<1.0) | RECOVERY ×2 net −4.21/−4.60 (churn nặng hơn sáng −2.5..−2.9) | −8.81$ (riêng C) |
| D 10:25–10:36 (P2-H2) | CR→IMP/down | TP ×3 +2.56/+3.51/+3.77 | 0 | HEDGE_TAKE_PAIR 10:30:43 **net −3.27 (ind −29.00)** · RECOVERY 10:34:09 net −3.35 | −0.06$ |

### 3.3 KPI "mua đuổi lặp lại" của HUMAN
- Rule: lặp lại ≥1–2 lần → áp C8. **ĐÃ TRIGGER 1 LẦN = cluster B 09:54–09:57** (span +4.22pts, 3 chase-events, net vẫn dương nhờ TP).
- Kết quả 6 chase-events: **4/6 TP dương (+$17.01 gross TPs), 2/6 rổ net âm (−2.93 · −3.27@10:30 nếu tính ind)**. Snapshot 1 ngày = **chase dương ròng** → §3.5.

### 3.5 KẾT LUẬN BASELINE (LUẬT 9 — metric trước khi tối ưu)
> C8 **KHÔNG** đo bằng "so với hôm nay" (hôm nay dương) mà bằng 3 thước: **(i) net tail của rổ chase (−2.93/−3.27/−4.21..−4.60 churn) giảm tần suất, (ii) replay 12d counterfactual (→ 11:0x: CHỈ MÀU SOI, không phải gate — HUMAN bỏ replay + pin), (iii) 3–5 phiên live kế tiếp (gate KPI §6)**. Baseline đã chốt: 6 chase-events/ngày · worst-cluster-net −4.60 · worst-ind −29.00 (case D — **11:0x: ĐÃ CHUYỂN VÀO PHẠM VI C8 qua G5**, retract §2.4 bản gốc).

---

## §4 OPTIONS (LUẬT 1 — Minimal + trade-off bằng số)
**1 hook duy nhất cho mọi option**: `_can_open_new_root(side, open_pos)` tại `scalp_strategy.py:665` (gate M3 đã cô lập 6 sites §1-B1) + 5 keys config mới.
**Chứng minh minimality (Luật 1)**: C8-Unified = 5 config keys + ~14 dòng trong 1 hàm + 2 dòng tracking `last_hedge_leg_ts` = **không state machine mới, 0 dependency** ✓.

> **Bảng counterfactual BẢN SƠ (đã BỎ — lỗi static-anchor)**: O1 "−6.16 · O2 −9.9 · O3 ~0" — bản gốc tính anchor từ entry đầu chùm như thể vẫn còn mở. **Thay bằng số verify §0.1 (per-second live-open, DB RO):**

| Option | Rule | Counterfactual VERIFY (HUMAN-window 08:41:20→10:09:17, 36 root) | Rủi ro chính |
|---|---|---|---|
| **O1 window-3′ (spec HUMAN gốc)** | anchor 3′ | chặn B_0919 nhưng chặn nhầm 3 TP (−6.16 theo HUMAN recalc; **không re-verify độc lập — không cần vì đã LOẠI**) | window cắt episode → chặn thiếu/lệch |
| **O2 live-anchor (nguyên bản)** | max span NAKED-live > 1.0 → chặn | **chặn 1/1 rổ chase đỉnh (B_0919 −2.93) · TP-loss = $0 · Δ +$2.93** (7 lệnh thắng TP/EXIT trong cửa sổ đều qua gate: A1/A2/B1/B2/B3 = 0 live-L tại giây vào) | chỉ cứu "đuổi đỉnh >1.0", không cứu rổ dup/underwater/post-leg |
| **O3 hybrid only-when-red** | O2 + net<0 | **DEAD CODE (verify §0.1-2): tại điểm G3 fire, NAKED-live bên dưới LUÔN dương → net<0 không đồng thời → O3 ⊆ O2, không giá trị độc lập → LOẠI** | — |
| **O4 giữ nguyên (monitor-only)** | 0 dòng | giữ +$17 net chase; 9 rổ lỗ −2.5..−4.6 (SUM −22.25/7 rổ trong cửa sổ) vẫn trả | phiên adverse = churn tiếp |
| **★ C8-UNIFIED = O2 + G1 + G2 + G4 + G5 (PHÊ DUYỆT)** | 4 hàng rào vật lý (§4.5) | **chặn 7/7 rổ lỗ, TP-loss = 0, Δ = +$22.25** (SUM −22.25 verify: B_0843_2 −2.51 · B_0844 −2.74 · B_0914 −3.07 · B_0919 −2.93 · B_0939 −3.51 · B_1000_2 −4.21 · B_1001 −3.27) · **extended-window (+10:09→nay): +1 rổ chặn (B_1034 −3.35, G4) · 1 winner bị chặn (10:30:36, +3.01, G4) → Δ full-day ≈ +$22.59** | G4 chặn lệnh "vào thấp dưới root-đang-kéo-sâu" = có thể chặn 1 vài TP lẻ trong whipsaw (by-design trade-off, KPI follow-up) |

### 4.5 C8-UNIFIED SPEC (4 hàng rào + 5 config keys) — verify trên dữ liệu thật 15/10
| Gate | Điều kiện chặn (cùng chiều, root mới @px, side s=±1) | Nguồn dữ liệu | Cứu được (15/10) |
|---|---|---|---|
| **G1 FWD_STEP** | `0 < Δ_near < 0.35` (Δ_near = px−entry của root cùng chiều GẦN NHẤT đang mở, ký hiệu theo s) | open_roots (M1 data, không cần state mới) | B_0914 (+0.287, −3.07) — sửa lỗ hổng "quên 0.35 sau 5s" của M3 (M3 chỉ chặn <0.35 trong-tick) |
| **G2 DUP_PULLBACK** | `−0.25 < Δ_near ≤ 0` (vào trùng giá/pullback quá sát) | như G1 | B_0843_2 (−0.191, −2.51) · B_0939 (−0.003, −3.51) · **giữ 100% pullback-thắng ≥ −0.25 (09:57:10 −0.261 · 09:14:26 −0.298 · 09:38:10 −0.505)** |
| **G3 O2_SPAN** | `max(Δ_naked) > 1.00` (Δ với MỖI root NAKED cùng chiều đang mở) | open_roots + NAKED = root chưa có leg-open | B_0919 (+1.418, −2.93; ind −10.74) — đúng "mua đuổi đỉnh" Red Team |
| **G4 PRE_HEDGE / UNDERWATER** | `Δ_near < −0.90` (root gần nhất đã âm sâu, cách vạch khóa −1.2 chỉ 0.3) | open_roots | B_1000_2 (−0.969, −4.21) · B_1034 (−11.74 extended, −3.35) · **giữ lệnh −0.867 (TP +3.39)** |
| **G5 POST_LEG_30S** | `0 < now − last_hedge_leg_ts ≤ 30s` (vừa mở chân HEDGE ≤30s → đóng băng root mới) | 1 biến tracking (2 dòng: set khi leg open) | B_1001 (13s, net −3.27 · **xóa ind −29.00**) · B_0844 (25s, −2.74) |

**Config (append-only, `src/config.py`)**: `C8_ENABLE=True` · `MAX_IMPULSE_SPAN_PTS=1.00` (⅔×TP) · `MIN_PULLBACK_STEP_PTS=0.25` · `MAX_ADVERSE_STACK_PTS=0.90` · `POST_HEDGE_COOLDOWN_SEC=30.0` — **1 flag revert toàn bộ = `C8_ENABLE=False` (1 dòng, không cần redeploy lần 2)**.
**Phạm vi**: áp cho mọi root mới cùng chiều (KHÔNG filter M0 — verify cho thấy chặn đúng cả rổ CREEP 10:00/10:25; giữ filter IMPULSE-only = bỏ G4/G5 mất 5/7 rổ). Log 1 dòng `[GATE] C8_SKIP reason=G?` khi chặn (throttle 10s/thay-reason — 6 call-sites × tick).
**Composite M3 (ghi nhận 11:2x, verifier note)**: M3-existing `abs(last_px−entry) < 0.35` (2 chiều) chạy TRƯỚC C8 → preempt band G1/G2 tại px-quyết-định → G1/G2 = belt-and-suspenders cho case px-lệch limit-fill/cross-tick (chính là lỗ hổng M3) · pullback-thắng vùng −0.25…−0.35 có thể bị M3 chặn → đo qua KPI iii (§6), không phải bug C8.

### 4.4 Limitation (LUẬT 3 — còn gì C8 KHÔNG cứu)
- Rổ "solo cluster-top bị reversal" khi không có root cùng chiều đang mở (vd top-1 của 10:00 cluster) = G4 chỉ chặn khi root gần nhất < −0.90 → tail ind (−14.5pts) vẫn có thể hiện nhưng **net luôn cap PSL −6.48 / HEDGE_TAKE net −3.27** (by P2-H design). C8 = giảm TẦN SUẤT rổ, không phải triệt tail (B3 bất diệt §2).
- Conflict-check C7: C7 guard `M0∈{RANGE,CREEP}` + đóng lệnh · C8 chặn lệnh mới — 2 nhánh độc lập; pair C7 10:50:39 (mở 10:48:42/10:49:05) **cả 2 entry qua C8 (flags rỗng)** ✓ không collision.

---

## §5 SANITY CHECK THIẾT KẾ (LUẬT 8 — ✅ đã CHẠY + VERIFY trong §0.1, không phải thiết kế chưa chạy)
### 5.1 REPL per-second live-open (ĐÃ CHẠY — kết quả in §0.1, bảng A1..B3)
Kỳ vọng đã khớp: O2 chặn đúng 1/6 (A3 +1.418) · TP-loss 0 · B_1001 chỉ bị G5 chặn (13s sau leg).
### 5.2 REPLAY 12d — **KHÔNG CÒN LÀ GATE** (HUMAN directive 11:0x: bỏ replay + không ép giữ pin 565; giữ file `_replay_hedge.py` như reference đọc, không block merge)
Baseline tham chiếu (đã biết): B hiện tại = +3780.83/12d · worst −6.96 (tick-overshoot, D2-override). C8 chỉ chặn entry → volume giảm → delta replay chỉ là SOI, không phải điều kiện duyệt.
### 5.3 Unit test `test_c8.py` (GATE THẬT — chạy trong worktree)
8 cases: (1) G3: span NAKED-live >1.0 chặn (repro A3) · (2) span ≤1.0 cho qua (repro A2 +0.436) · (3) S đối xứng · (4) G1: 0<Δ<0.35 chặn (repro B_0914) · (5) G2: |Δ|≤0.25 pullback chặn (repro B_0939 −0.003) mà Δ≤−0.25 cho qua (repro 09:57:10 −0.261) · (6) G4: Δ<−0.90 chặn (repro B_1000_2) mà −0.90≥Δ≥−0.25 cho qua (09:27:28 −0.867) · (7) G5: 13s/25s sau leg chặn, 31s+ cho qua · (8) `C8_ENABLE=False` → toàn bộ pass (parity 100% như C5-G2, pin giữ nguyên khi off).

---

## §6 TEST GATES & ACCEPTANCE KPI (cycle C8) — CẬP NHẬT 11:0x theo HUMAN directive
**Gate thực thi (CHẠY trong worktree `s4-hedge`, không đụng runtime gốc):**
- `py_compile` 3 files (config/scalp_strategy/scalp_executor) · **`test_c8.py` 8/8 (§5.3)** = GATE THẬT.
- `test_m1` 10/10 · `test_m3` 6/6 · `test_s2` 9/9 giữ (C8 chỉ chặn entry — exit-set không đổi, đã verify).
- **`test_offline` pin: KHÔNG ÉP GIỮ 565** (HUMAN directive) — C8 chặn entry → volume offline thay đổi là **dự kiến**; ghi pin MỚI vào STATE làm reference (soi xu hướng, không block merge).
- `_replay_hedge.py` 12d: **chạy như reference đọc** (soi delta PnL/worst-cluster), **KHÔNG phải điều kiện duyệt** (bản gốc §5.2 đã xóa gate này).
- Verifier sub-agent sau S3 (AGENTS.md L2+ rule).

**KPI live 24h sau deploy (accept/pass-fail):**
(i) **G3-chase = 0**: entry cùng chiều có max-span so NAKED-live > 1.0pt (mọi M0) · (ii) cluster-rổ-âm (net cặp ≤ −2.48) giảm tần suất vs baseline 7/7 ngày 15/10 · (iii) TP/day Δ vs baseline ngày **≥ −20%** (vượt → nâng `MAX_IMPULSE_SPAN_PTS` 1.0→1.25, hoặc G4 −0.90→−1.05; fail nặng → revert 1 dòng `C8_ENABLE=False`) · (iv) burst cùng-tick = 0 (M3 không bị ảnh hưởng) · (v) **C7 CROSS_RESCUE vẫn fire** (đã fire cặp đầu 10:50:39 net +0.49$; C8 pair-10:48/49 flags rỗng ✓ không collision) · (vi) **G5 cooldown không nuốt lệnh hợp lệ**: đếm entry bị chặn reason=G5 + pnl của các lệnh lẽ ra sẽ mở (follow-up, không block).

**Conflict-check C7 (đính chính 11:0x)**: C7 guard `M0∈{RANGE,CREEP}` (đóng cặp) · C8 gate mọi root mới (mở) — 2 nhánh độc lập **và đã verify bằng data thật** (pair C7 10:48/49 không bị C8 chặn) ✓.

**Parameter (5 keys, §4.5)**: `C8_ENABLE=True` · `MAX_IMPULSE_SPAN_PTS=1.00` (⅔×TP=1.5; HUMAN chốt) · `MIN_PULLBACK_STEP_PTS=0.25` · `MAX_ADVERSE_STACK_PTS=0.90` · `POST_HEDGE_COOLDOWN_SEC=30.0` — **1 flag revert toàn bộ = `C8_ENABLE=False`**.

---

## §7 QUY TRÌNH THỰC THI (LUẬT 6 — mỗi step: 1 ACT + 1 OBSERVE; 3-strike; bot 97539 KHÔNG đụng trước ROL)
```
PRE-GATE (HUMAN 11:0x): ✅ PHÊ DUYỆT C8-Unified + restart-window = ROL 21:45Z hoặc khi open=0
S1 [ĐÃ XONG 11:0x] REPL per-second (§0.1) [OBS] 3/3 claim verify: O2 chặn 1/6 (A3) · 0 TP-loss · G5 chặn Case D
S2 [ACT] code C8-Unified trong worktree s4-hedge: 5 config keys + ~14 dòng @ _can_open_new_root (L665)
        + 2 dòng tracking last_hedge_leg_ts + log [GATE] C8_SKIP + test_c8.py (8 cases §5.3)
   [OBS] py_compile pass + test_c8 8/8 + test_m1/m3/s2 giữ
S3 [ACT] gate-green: run _replay_hedge.py CHỈ reference (không block) · ghi pin MỚI reference (không ép 565)
   [OBS] bảng reference + verifier sub-agent PASS → commit s4-hedge (CHƯA merge) → STATE entry
S4 [HUMAN final GO tại ROL 21:45Z HOẶC khi open=0] ff-merge main + restart 1 LẦN (canonical boot)
   [OBS] boot: M2 restore day$ + log C8 active (1 dòng [GATE] C8_ON) + PID mới + zombie-check
S5 [OBSERVE đến ROL/phiên kế] KPI §6 (i..vi)   [REFLECT] keep / chỉnh 1 param / revert 1 dòng
```
- **Anti-loop (quy tắc 3-strike)**: mỗi step fail 3 lần → dừng + báo HUMAN (không tự đổi hướng).
- **Zero-downtime**: đúng 1 merge + 1 restart (chuẩn boot: `cd XAU_SCALP5 && SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem nohup .venv/bin/python main.py >> "logs/$(date -u +%F)_scalp5.out" 2>&1 &`).
- Verifier sub-agent sau S3 (theo AGENTS.md L2+ rule) trước khi S4.
- **S2/S3 chạy NAY trong worktree (HUMAN directive 11:0x)** — worktree tách biệt, merge/restart CHỈ tại S4 (ROL 21:45Z = 04:45+07 ngày 16/10, hoặc HUMAN gọi khi open=0).

---

## §8 PEDAGOGICAL (LUẬT 10)
> **Analogy — "chặn xe bus ở bến"** (đính chính 11:0x theo live-anchor): sóng IMPULSE = xe bus 5 bến. Bến 1–3 (chân sóng) lên xe giá rẻ, còn ghế (TP +$3/lệnh). Bến 4–5 (đỉnh) mua vé giá cao, vừa lên xe "nhuộm" (reversal) → trượt (leg −5.13, root ind −10.74/−29.00). **Lỗi bản gốc: tính "giá vé bến 1" như thể vẫn còn bán khi xe đã chạy tới bến 4 (static anchor) → oan cho O2 (−9.9$)**. Tính đúng "ai đang ngồi trên xe lúc đó" (live-anchor): bến 1–3 đã đóng TP từ lâu, chỉ còn lệnh đuổi đỉnh (A3 +1.418) là bị chặn → **O2 cứu +2.93, mất $0**. C8-Unified = O2 + 3 hàng rào phụ: (G1/G2) không đứng trùng chỗ người đang ngồi · (G4) không nhồi thêm khi chuyến trước đã chìm sâu (−0.90, sắp chốt −1.2) · (G5) sau khi có hành khách phải "cấp cứu" (mở leg HEDGE), 30s không bán vé chuyến mới — chặn đúng vụ −29.00 (10:01, 13s sau leg). Số thật 15/10: 7/7 rổ lỗ chặn, 0 TP bị oan · C7 (cứu rổ chéo) fire cặp đầu 10:50:39 (+0.49$) không đụng hàng rào C8.
> **Công thức bất diệt** (first principles): `net_rổ_RECOVERY ≈ +$2.0 (root @+1.0pt) − $5 (leg @−2.5pt) ≈ −$3` — đây là **giá của slot-engine**, không phải bug; C8 chỉ **giảm số lần trả giá này**.

---

## §9 DECISION MATRIX (CẬP NHẬT 11:0x — HUMAN ĐÃ CHỌN)
| Mục tiêu | Option | Today counterf. (VERIFY §0.1) | Kết luận HUMAN |
|---|---|---|---|
| Chặn rổ lỗ max, giữ 100% TP thắng | **★ C8-Unified (O2+G1+G2+G4+G5)** | chặn 7/7 rổ (−22.25$), 0 TP-loss, Δ +$22.25 (HUMAN-window) · full-day +$22.59 | **PHÊ DUYỆT (11:0x)** — S2/S3 trong worktree ngay; S4 merge+restart tại ROL/open=0 |
| Không xả TP (bảo thủ) | O3 hybrid | DEAD CODE (verify: O3 ⊆ O2; O2 đã 0 TP-loss → O3 không có giá trị độc lập) | LOẠI |
| Spec gốc 3′ | O1 window | −6.16 (HUMAN recalc; chặn 3 TP nhầm) | LOẠI |
| Fallback nếu KPI §6 fail | O4 monitor | giữ +17$ chase; churn −2.5..−4.6 tiếp | chỉ dùng khi C8 fail (revert 1 dòng) |

**Quy tắc trigger (HUMAN 10:0x)**: chase lặp ≥1–2 lần → C8. **ĐÃ TRIGGER (cluster B 09:54) + HUMAN PHÊ DUYỆT 11:0x → C8-Unified CHẮC**, không cần vote replay.

**Deploy window (chốt)**: giữ PID 97539 đến **ROL 21:45Z (04:45+07 ngày 16/10)**; code+test ready trong `s4-hedge` trước đó; HUMAN có thể gọi S4 sớm khi **open=0** (lệnh của HUMAN). Merge = ff-merge main 1 lần + restart 1 lần canonical boot + zombie-check.

**Monitoring hôm nay (chỉ đọc, KPI §6):**
```bash
cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
tail -f logs/2026-10-15_scalp5.log | grep -E "ENTER|EXIT|CROSS_RESCUE|PRUNE|HEDGE|HB"
```
Đếm: (1) **chase-event G3** = entry cùng chiều max-span > 1.0 vs NAKED-live (mọi M0) · (2) **chase-rổ-âm** = exit pair net ≤ −2.48 · (3) **C7 rescues** — **ĐÃ ĐẠT 1/1 (10:50:39, net +0.49$ ✓)** · (4) rổ RECOVERY churn (baseline −3.3..−4.6: 10:13 −2.74 · 10:34 −3.35) · (5) X1 ghost = 0. Snapshot 11:0x: day$ ≈ +111 (115+ exits) · open 0 @10:50:39.

---
*File = PLAN + SPEC C8-Unified (AGENTS.md: code chỉ trong worktree `s4-hedge` theo S2/S3; bot runtime gốc & data (PID 97539) KHÔNG CHẠM đến S4). HUMAN 11:0x đã PHÊ DUYỆT C8-Unified → trạng thái: CHỜ S4 (ROL 21:45Z hoặc lệnh open=0).*
