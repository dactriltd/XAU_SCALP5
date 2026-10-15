# P2-H3 RESEARCH PLAN — IMPULSE SPAN CAP ("C8: Mua đuổi đỉnh sóng") · NGHIÊN CỨU CHUYÊN SÂU
> 15/10 10:4x+07 · **L1 PLAN-ONLY: KHÔNG CODE, KHÔNG ĐỤNG BOT ĐANG CHẠY (PID 97539 @09:49:38, chạy đến ROL 21:45Z)**
> Áp dụng bộ luật AGENTS.md (Karpathy): First Principles · Minimal Abstractions · Empirical · Baseline-First · Pedagogical
> Dữ liệu: `data/scalp5.db` (entry_log/exit_log/regime_log, đọc chế độ RO) · `logs/2026-10-15_scalp5.log` · `logs/scalp5_timeline_1510.csv`
> Nguồn "nội dung áp dụng": phân tích Red Team C8 (HUMAN 10:0x) + live-anchor refinement (Agent 10:1x, STATE §10:1x)

---

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
4. **Tail ind vs net** (B4): evidence 10:30:43 HEDGE_TAKE_PAIR (root 4877538554 L@4161.534 10:01:01 → exit 4147.033 = −14.5pts = **−$29.00 ind** · leg 4877540882 S@4160.196 → +$25.73 · **net −$3.27 ≤ −6.48 cap ✓**): top-entry cluster CREEP-span 0.73pts (<1.0 → **BẤT KỲ option nào cũng KHÔNG chặn được** — limitation ghi §4.4). C8 đánh giá trên **net cluster + tần suất tail**, không phải cảm giác con số ind.

---

## §3 EMPIRICAL BASELINE (LUẬT 3, 9) — Số thật tính đến 10:36
### 3.1 KPI ngày (read-only DB, 10:36)
| Chỉ số | Giá trị | Evidence |
|---|---|---|
| Day PnL (exit_log SUM từ 07:00) | **+107.79$ (115 exits)** | khớp in-memory status.json day$=107.79 @10:35:04 ✓ |
| M2 cross-check (09:49:44) | 46.29 (PRE-P2H, 53 exits) + 36.99 (P2-H, 35 exits) = **83.28 ≈ 83.29 restore ✓** | tuyệt đối (±0.01 rounding) |
| IMPULSE episodes hôm nay | **16** (regime_log 07:06→10:35; up 8/down 8, speed 0.52–1.44) | query §3.2 |
| Chase-events (>1.0pt vs anchor cùng chiều trong IMPULSE) | **6** (A:3 · B:3) | bảng 3.2 |
| C7 CROSS_RESCUE | **0 cặp** (M0 sáng nay đa số IMPULSE → C7 skip đúng thiết kế; replay dự báo ~0.75/ngày) | grep log + exit_log `like 'CROSS%'` |
| Open positions | **0** @10:35:04 (slot sạch) | status.json |

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
> C8 **KHÔNG** đo bằng "so với hôm nay" (hôm nay dương) mà bằng 3 thước: **(i) net tail của rổ chase (−2.93/−3.27/−4.21..−4.60 churn) giảm tần suất, (ii) replay 12d counterfactual, (iii) 3–5 phiên live kế tiếp**. Baseline đã chốt: 6 chase-events/ngày · worst-cluster-net −4.60 · worst-ind −29.00 (case D, ngoài phạm vi C8).

---

## §4 OPTIONS (LUẬT 1 — Minimal + trade-off bằng số)
**1 hook duy nhất cho mọi option**: `_can_open_new_root(side, open_pos)` tại `scalp_strategy.py:665` (gate M3 đã cô lập 6 sites §1-B1) + 1 key config mới.
**Chứng minh minimality (Luật 1, câu hỏi "≤15 dòng thuần?")**: O2 = 1 key config + ~5 dòng trong hàm (so sánh px với min/max entry của NAKED cùng chiều CÒN MỞ khi `m0_regime=="IMPULSE"`) = **10 dòng, 0 dependency, 0 state mới** ✓. Không cần thư viện (bất kỳ thư viện) nào — qua test Luật 1.

| Option | Rule (chặn nếu) | Counterfactual hôm nay (6 events) | Rủi ro chính |
|---|---|---|---|
| **O1 window-3′ (spec HUMAN gốc)** | anchor = entry tốt nhất cùng chiều trong 3′; px−anchor > 1.0 | Chặn 4/6 — **lọt 2**: 4146.158 (cách 4′01″) & 4158.842 (4′01″) → **spec tự mâu thuẫn ví dụ chính nó** (cùng lỗi với 10:1x) | window 3′ < chu kỳ chase 4–5′ → chặn thiếu hệ thống |
| **O2 live-anchor (đề xuất)** | anchor = entry tốt nhất NAKED **còn mở** cùng chiều (không time-window); M0==IMPULSE; L: px−min(entries-L-live) > `MAX_IMPULSE_SPAN_PTS` 1.0 → chặn · S đối xứng: max(S-live)−px > 1.0 | Chặn **6/6** · đổi: giữ tail −2.93/−3.27 nhưng **mất TP +3.94/+3.07 (A) + TP cluster B (+$11.76)** → **−9.9$ today = CHẤP NHẬN NHƯ BẢO HIỂM** | phiên "runaway lời" (B) bị thiệt — TP volume ↓ |
| **O3 hybrid only-when-red** | O2 + `net_cluster_chạy < 0` (realized exits + unrealized theo tick px của NAKED live cùng chiều) | A: xanh → không chặn (giữ +7.08 ✓) · B: xanh đến 4156.865 → chặn 4159.x nếu net đã âm → **~0$ today, giữ được TPs** | +3 dòng (tính net O(N)); trễ 1 tick so O2 |
| **O4 monitor-only** | — | giữ +$17 net hôm nay; tail −29 ind vẫn hiện (net đã cap −3.27 ✓) | tiếp tục trả churn −4.2/−4.6 phiên adverse |

### 4.4 Limitation (LUẬT 3 — ghi thẳng, không che)
- **Case D (10:30, ind −29.00) KHÔNG bị C8 chặn** (span cluster CREEP 0.73 < 1.0 → mọi threshold ≥1.0 đều vô hiệu). Tail "solo cluster-top bị reversal" là **bệnh khác (C9, chưa chỉ định)**; net vẫn cap −6.48 → giữ observe-only.
- C8 = **giảm tần suất rổ chase** (B5), không phải triệt tiêu tail (B3 bất diệt).
- 10:30:43 HEDGE_TAKE_PAIR fire vì leg +1.5pts & M0≠IMPULSE (wall semantics) — hành vi đúng spec P2-H, không phải lỗi.

---

## §5 SANITY CHECK THIẾT KẾ (LUẬT 8 — chạy ĐẦU CYCLE, không chạy ở L1)
### 5.1 REPL tĩnh (10s, deterministic, output kiểm tay được)
```python
# SANITY CHECK: 6 chase-events × 3 options — bảng chặn
events = [(A,4146.158),(A,4146.594),(A,4147.576),(B,4156.865),(B,4159.103),(B,4158.842)]
anchors = {A: 4144.630, B: 4152.647}
# kỳ vọng: O1 block=4 (lọt 2) · O2 block=6 · O3 block=0-2 (tuỳ net lúc tick)
```
→ Kết luận dự kiến: O2 là option duy nhất chặn đủ ví dụ HUMAN (4146.158) → O1 loại trừ ngay.
### 5.2 Replay 12d counterfactual (3 thể, `_replay_hedge.py` đọc DB RO)
Baseline B = **+3780.83** (9 cặp rescue, UNWOUND 0, worst −6.96) · chạy B+O2 · B+O3.
**Acceptance (LUẬT 9)**: `PnL(B+O?) ≥ PnL(B) × 0.99` **VÀ** `worst-cluster-net giảm ≥ 50% (−4.60 → ≤ −2.3)` **VÀ** `TP-count Δ ≥ −20%`. Fail 1 tiêu chí → không deploy, về O4.
### 5.3 Unit test `test_c8.py` (6 cases): (1) IMPULSE-up span>1.0 chặn L · (2) S đối xứng chặn · (3) RANGE/CREEP KHÔNG chặn (engine giữ nguyên) · (4) span ≤1.0 cho qua · (5) 1 NAKED live cùng chiều = anchor nó · (6) pullback (px về ≤1.0) cho vào lại.

---

## §6 TEST GATES & ACCEPTANCE KPI (cycle C8)
- `py_compile` 3 files · **test_offline pin: SẼ THAY ĐỔI** (C8 chặn entry → pin ON 565 giảm) — quy tắc Luật 1: **không ép giữ 565**, ghi sổ pin mới + replay A/B làm baseline · `test_m1` 10/10 giữ · `test_m3` 6/6 giữ · `test_s2` 9/9 giữ · exit-set test_offline **KHÔNG đổi** (chặn-entry không sinh exit row — đã verify: không có reason mới).
- **KPI live 24h sau deploy (accept/pass-fail)**: (i) chase-events (M0=IMPULSE, >1.0pt vs live-anchor) = **0** · (ii) cluster-IMPULSE net ≥ 0 · (iii) TP/day Δ vs pin-cũ **≥ −20%** (vượt → nâng `MAX_IMPULSE_SPAN_PTS` 1.0→1.25 hoặc chuyển O3) · (iv) burst cùng-tick = 0 (M3 không bị ảnh hưởng) · (v) C7 CROSS_RESCUE vẫn fire bình thường (không conflict: C7 đóng lệnh, C8 chặn lệnh — 2 nhánh độc lập, guard 1 cặp/tick giữ).
- **Parameter**: `MAX_IMPULSE_SPAN_PTS = 1.00` (Luật 0: = ⅔ × TP_POINTS 1.5 — chặn khi sóng đã chạy ⅔ biên độ lãi mục tiêu, còn ⅓ buffer cho slippage+spread; HUMAN chốt 1.00 trong Red Team) · `C8_ENABLE` flag = **1 dòng revert** (rollback an toàn không cần redeploy lần 2 nếu KPI iii fail nặng).
- Conflict-check với C7: C7 guard `M0∈{RANGE,CREEP}` · C8 chỉ `M0==IMPULSE` → **0 giao tập** (mutually exclusive regimes) ✓.

---

## §7 QUY TRÌNH THỰC THI (LUẬT 6 — mỗi step: 1 ACT + 1 OBSERVE; 3-strike; KHÔNG đụng bot hôm nay)
```
PRE-GATE (HUMAN): chọn O2/O3/O4 + xác nhận restart-window (open=0 hoặc ROL 21:45Z)
S1 [ACT] chạy §5.1 REPL      [OBS] bảng 6-event khớp dự đoán (O1=4 · O2=6)
S2 [ACT] code C8 worktree s4-hedge (~10 dòng + 1 config + test_c8) [OBS] py_compile + 6/6
S3 [ACT] replay 12d ×3 thể   [OBS] bảng PnL/worst-cluster/TP-count
S4 [ACT] pin mới + m1/m3/s2  [OBS] gate green → commit + push s4-hedge (CHƯA merge)
S5 [HUMAN approve] ff-merge main + restart 1 LẦN (open=0)          [OBS] boot: M2 restore + SPAN_CAP log line
S6 [OBSERVE 24h] KPI §6      [REFLECT] keep / nâng threshold / revert (1 dòng flag)
```
- **Anti-loop (quy tắc 3-strike)**: mỗi step fail 3 lần → dừng + báo HUMAN (không tự đổi hướng).
- **Zero-downtime**: đúng 1 merge + 1 restart (chuẩn boot: `SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem nohup .venv/bin/python main.py >> "logs/$(date -u +%F)_scalp5.out" 2>&1 &`).
- Verifier sub-agent sau S2 (theo AGENTS.md L2+ rule) trước khi S5.

---

## §8 PEDAGOGICAL (LUẬT 10)
> **Analogy — "chặn xe bus ở bến"**: sóng IMPULSE = xe bus 5 bến. Bến 1–3 (chân sóng) xe đi chậm: lên dễ, vé rẻ, còn ghế (3 lệnh đầu cluster A/B = TP +$3 mỗi lệnh). Bến 4–5 (đỉnh sóng) xe đã nổ máy: mua vé giá cao, vừa lên là xe "nhuộm" (reversal) → bị trượt (leg −5.13, root ind −10.74/−29.00). **Nhưng số liệu 15/10 sáng: xe hôm nay chạy xuyên bến 4–5 mà LỜI** (cluster A +7.08 · B +3.05) — nên luật "cấm lên bến cuối" (O2) chỉ hợp lệ khi **12 phiên replay chứng minh bến 4–5 thua ròng** (tail net), chứ không phải vì hình hài. O3 = "chỉ cấm lên bến cuối **khi xe đã chạy sai hướng** (cluster âm)" — bản linh hoạt. O1 (sổ 3 phút) = "nhìn lại 3 phút trước để quyết" — **đã bị 15/10 chứng minh lỗi** (chase chu kỳ 4–5 phút, sổ 3 phút nhìn không thấy bến 1).
> **Công thức bất diệt** (first principles): `net_rổ_RECOVERY ≈ +$2.0 (root @+1.0pt) − $5 (leg @−2.5pt) ≈ −$3` — đây là **giá của slot-engine**, không phải bug; C8 chỉ **giảm số lần trả giá này**.

---

## §9 DECISION MATRIX CHO HUMAN + MONITORING HÔM NAY (không code, bot 97539 giữ nguyên đến ROL 21:45Z)
| Mục tiêu | Option | Today counterf. | Tail net | Độ phức tạp |
|---|---|---|---|---|
| Không xả TP xanh (data 15/10 ủng hộ: 4/6 chase TP) | **O3 hybrid** | ~0$ | giảm phần chặn được | ~13 dòng |
| Bảo hiểm tail tối đa (chặn 6/6) | O2 live-anchor | −9.9$ | giảm ≥50% (mục tiêu) | ~10 dòng |
| Chưa quyết, gather data | O4 monitor | +17$ | không đổi | 0 |
**Quy tắc trigger (HUMAN 10:0x)**: chase lặp ≥1–2 lần → C8 vào cycle kế. **Đã trigger 1 (cluster B)** → nếu thêm ≥1 sự kiện chase-rổ-âm trước ROL → O2/O3 chắc; nếu không → replay 12d (§5.2) vote.

**Monitoring hôm nay (theo lệnh HUMAN, chỉ đọc):**
```bash
cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
tail -f logs/2026-10-15_scalp5.log | grep -E "ENTER|EXIT|CROSS_RESCUE|PRUNE|HEDGE|HB"
```
Đếm 3 KPI: (1) **chase-event mới** = entry cùng chiều cách live-anchor >1.0pt trong M0=IMPULSE (regime log 1′) · (2) **chase-rổ-âm** = exit pair net ≤ −2.48 có leg mở trong 60s sau chase-event · (3) **C7 rescues** (hy vọng ≥1 khi M0 về RANGE/CREEP chiều — sáng 0 do M0 đa số IMPULSE).

---
*File = PLAN CHỈ (AGENTS.md L1 report-only). Mọi code trong worktree `s4-hedge` sau S2 §7; bot runtime gốc & data (PID 97539) KHÔNG chạm. Chờ HUMAN: chọn O2/O3/O4 (§9).*
