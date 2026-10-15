# ORDER-TYPES INVENTORY — DANH SÁCH TỔNG HỢP KIỂU LỆNH · ĐIỀU KIỆN VÀO · ĐIỀU KIỆN RA (15/10)
> 15/10 15:1x+07 · L1 REPORT-ONLY · Nguồn sự thật: **code deploy `8340c96`** (S4 merge C8-Unified) + `logs/2026-10-15_scalp5.log` (07:00→15:12+07)
> Mục đích: SOT cho các cycle tối ưu kế tiếp (P2-H4). Mọi con số điều kiện lấy từ `src/config.py` + `src/scalp_strategy.py` (dòng thật).

---

## §0 PRECONDITION TOÀN CỤC (áp dụng MỌI lệnh ROOT)

| Gate | Điều kiện | Tham số (config) |
|---|---|---|
| Window | 00:00–21:45Z · ROL = chặn entry + đóng TOÀN BỘ | `windows ((0, 1305),)` · `ROL 21:45Z` |
| Slot | open < 8 (4 root + 4 leg) · root ≤ 4 | `K_CONTEXT=8` · `MAX_ROOT_POSITIONS=4` |
| M3 burst (P2-H) | root cùng chiều: giãn ≥5s · |Δpx| ≥ 0.35pts · chống burst in-tick (sự cố 07:05 15/10) | `MIN_ROOT_GAP_SEC=5` · `MIN_ROOT_STEP_PTS=0.35` |
| C8-Unified (P2-H3, 11:54 live) | G1 `0<Δ<0.35` · G2 `−0.25<Δ≤0` · G3 NAKED-span >1.0 · G4 Δ<−0.90 · G5 30s-sau-leg-HEDGE | 5 keys: `C8_ENABLE` · `MAX_IMPULSE_SPAN_PTS=1.00` · `MIN_PULLBACK_STEP_PTS=0.25` · `MAX_ADVERSE_STACK_PTS=0.90` · `POST_HEDGE_COOLDOWN_SEC=30.0` |
| G2-A | chặn v0 trong vùng LVL+EXT15 (không burn re-fire slot) | `_g2_block()` |
| C8 composite note | M3-existing (abs<0.35) chạy TRƯỚC C8 → G1/G2 = belt-and-suspenders cho px-lệch limit-fill/cross-tick | docs/P2-H3 §4.5 |

---

## §1 LỆNH ROOT (6 kiểu)

| # | Kiểu | Trạng thái | Khi nào VÀO (điều kiện trigger) | Khi nào RA (điều kiện thoát) |
|---|---|---|---|---|
| 1 | **MOM1-PULLBACK L** | ★ CHẾ ĐỘ HIỆN TẠI | Close nến M1: `mom_net = px − close_m1[−3] ≥ +1.5pts` (`MOM_THR_PTS`) → arm **mua @ đỉnh_nến −0.8** (`MOM_PUB_PTS`), hiệu lực `MOM_ARM_LEN=1` nến · fill khi px ≤ arm_px · tối đa `MOM_MAX_PER_CANDLE=1` lệnh/nến (nến mạnh ≥2.5 → +1) · FZ: đỉnh chạm H-zone (test ≥2 lần) → FADE (đảo S @ đáy+0.8) hoặc SKIP (debounce) | Solo (NAKED): **PSL −3.0pts** (cầu chì, ưu tiên 1) · **TP +1.5pts** (broker, `MOM_EXIT_POLICY=NOW` → TP cố định, không ratchet) · **TIME 10′** (`MOM_TIME_STOP`; MOM1: chỉ PnL≥0) · **S_BREAK** (lỗ + phá S-confirmed nghịch ≥ `S_CHAIN_BREAK=0.5`) · **C7** (rescue cặp) · **ROL** · pnl ≤ **−1.2** (`HEDGE_LOCK_PTS`) → **đẻ HEDGE leg** (dòng 6 → máy rổ) |
| 2 | **MOM1-PULLBACK S** | ★ CHẾ ĐỘ HIỆN TẠI | Mirror: `mom_net ≤ −1.5pts` → arm **bán @ đáy_nến +0.8** · fill px ≥ arm_px · FZ L-zone: FADE → đảo mua | Tương xứng dòng 1 (S ra khi phá S-đỉnh nghịch) |
| 3 | **B_SNEO L/S** | Fallback (TẮT: `MODE=MOM1`) | S_đáy confirmed·chưa broken, touch 1–2 (`MAX_TOUCH=2`; T3+ = S kiệt = chặn) + px bật ≥ `S_BOUNCE_PTS=2.5` khỏi mức → mua tại px · S_đỉnh mirror → bán | TP 1.5 · PSL −3 · DRIFT-flip (d5m về 0 khi lỗ) · S_BREAK ±0.5 · TIME 15′ (`TIME_STOP_MIN`, vô điều kiện) · ROL |
| 4 | **R1 STALL-TOP (S-limit)** | Active (gated) | M0 ≠ IMPULSE + H-zone strong·alive + 3 nến M1 gần không phá P+`STALL_TOL=0.25` + net5(C−O)<0 + chờ ≥`STALL_WAIT_M1=3′` sau t_conf → arm **SELL-limit @ P−`FADE_PTS=2.5`**, TTL `LIMIT_TTL=15′` · 1 lệnh/zone/ngày/hướng (`r1r2_done`) · fill khi px chạm xuống limit | **4-lớp riêng (`r1r2=True`)**: PSL · TP 1.5 · **DRIFT-FLIP** (`DRIFT_FLIP_TICKMIN=2`: 2 close M1 adverse liên tiếp khi lỗ, m1-proxy) · ROL — **KHÔNG có TIME** |
| 5 | **R2 STALL-BOTTOM (L-limit)** | Active (gated) | Mirror R1 → **BUY-limit @ P+2.5** | Tương xứng dòng 4 |
| 6 | **HEDGE leg C5** | LIVE (`HEDGE_ENABLE=True`) | Root **pnl ≤ −1.2pts** (`HEDGE_LOCK_PTS`, ≈ −$2.40/leg) → tự mở **leg đối xứng 0.02lot** → rổ LOCKED (net frozen ≈ −3.36$ gồm spread) · KHÔNG qua M3/C8 (slot leg riêng) | **Máy rổ** (`_manage_hedge_basket`): **PSL_BASKET** net ≤ **−$6.48** (`PSL_BASKET_USD`, cầu chì rổ, ưu tiên đầu) · **HEDGE_TAKE_PAIR** (giá tại cản + bounce ≥ `HEDGE_BOUNCE_CONFIRM_PTS=0.4` & leg lãi ≥ `HEDGE_MIN_PROFIT_PTS=1.5` & M0≠IMPULSE → đóng CẢ CẶP) · **BASKET_TIME** (`HEDGE_TIMEOUT_NOWALL_MIN=15′` không cản / `HEDGE_TIMEOUT_MIN=30′` có cản, floor `BASKET_TIME_MAX_LOSS_USD=6.48`) · **PRUNE_RECOVERY** (giá quay thuận ≥ `HEDGE_RECOVERY_PTS=1.0`pts → đóng leg, root chạy tiếp solo) · **PRUNE_BREAK** (phá cản ≥ `HEDGE_BREAK_PTS=1.0` → đóng cặp) · **PRUNE_SPAN** (không cản trong `HEDGE_MAX_SPAN_PTS=4.5`pts → đóng leg) · **ROL** (đóng tất cả) · Cản phải cách giá ≥ `HEDGE_WALL_PAD_PTS=0.3` |

## §2 C7 CROSS_RESCUE (P2-H2 — loại "vào-là-ra": không mở lệnh, chỉ CỨA rổ trước khi nó ra đời)

**Khi nào fire (đóng 2 lệnh NAKED trong 1 tick, 1 cặp/tick):**
- Guard: `M0 ∈ {RANGE, CREEP}` · 2 NAKED cùng chiều ΔE_entry < TP (toán HUMAN: phải dùng ngưỡng **peak** để rescue đủ loser trong vùng nguy hiểm)
- **WINNER**: NAKED dương, peak_fav ≥ `CROSS_RESCUE_PEAK_PTS=0.9`pts & đã giật lùi ≥ `CROSS_RESCUE_PULLBACK_PTS=0.25` (đang chững)
- **LOSER**: NAKED âm trong `[−CROSS_RESCUE_LOSS_MIN_PTS, −CROSS_RESCUE_LOSS_MAX_PTS] = [−1.15, −0.45]pts` (vùng TRƯỚC ngưỡng khóa −1.2)
- **NET**: (pnl_win + pnl_lose) × $2/pt ≥ `CROSS_RESCUE_MIN_NET_USD=+$0.30`
- EXIT: `CROSS_RESCUE_WIN` + `CROSS_RESCUE_LOSER` · KHÔNG chạm: chân HEDGE, root đang có rổ mở, vị thế đã EXIT tick này
- **🔍 FINDING (đợi HUMAN chốt)**: code-comment L931 (toán HUMAN) ghi vùng nguy hiểm "[-1.15, **−0.60**]" nhưng config `LOSS_MAX_PTS=0.45` → **thừa số 0.45 hay 0.60 cần chốt trước khi widen band**

## §3 ORPHAN_CLEANUP (P2-H M1)
Leg mồ côi (root đã đóng thật trên sàn — vd EXIT_SYNC/PSL-ratchet) → **đóng leg tick đầu** (không chờ máy rổ). Guard: `open_pos` rỗng đột ngột = RPC stall/sudden-empty → **KHÔNG kết luận mồ côi** (chống chuỗi sự cố 02:25→02:50: registry wipe → 8 exit rời rạc).

## §4 SOLO-EXIT STACK (trình tự ưu tiên, 1 tick — code L1162–1220)
```
ROL (đóng tất cả, ưu tiên tuyệt đối khi ROL)
└─ root CÓ leg → MÁY RỒ (dòng 6, skip solo-loop)
└─ root NAKED: PSL −3.0 (đầu)
   → R-position: TP | DRIFT | ROL (4 lớp, không TIME)
   → MOM1 NOW: TP 1.5 | S_BREAK | TIME 10′ (PnL≥0) | ROL
   → B_SNEO:   TP | DRIFT-flip | S_BREAK ±0.5 | TIME 15′ | ROL
   → [hedge_on & chưa EXIT tick này] → máy rổ xét mở leg (−1.2)
Sau solo-loop: C7 _pre_lock_rescue (1 cặp/tick)
Prune-guard registry (grace 45s · open_pos rỗng = giữ)
```
*Thực tế: C5 intervene tại −1.2 < PSL −3.0 → PSL solo chỉ còn ý nghĩa fallback (gap <1 tick); loss-floor thật của root = máy rổ (PSL_BASKET −6.48 / BASKET_TIME / PRUNE_*).*

## §5 SỐ THẬT HÔM NAY (evidence, log 15/10 07:00→15:12+07, PID 97539 + 17027)

| Hạng mục | Số |
|---|---|
| ENTER | **91** = ~66 root (MOM1-PULLBACK) · 25 HEDGE-leg · **0 R-arm** (M0 đa số IMPULSE → gate R1/R2 chặn) |
| EXIT | **87** = TP×30 · PRUNE_RECOVERY×22 · PRUNE_BREAK×16 · HEDGE_TAKE_PAIR×6 · BASKET_TIME×4 · ORPHAN×4 · PRUNE_SPAN×2 · PSL×1 · CROSS_RESCUE×2 (1 cặp @10:50:39, net +0.49$) |
| **C8 (11:54→15:12, ~3.3h)** | **16 blocks = G4×9 + G5×7 · G1/G2/G3 = 0** (G1/G2 bị M3 preempt ✓ theo design · chưa có NAKED-live span >1.0) |
| Snapshot 15:12 | day$ **+117.31** · open=1 · PID 17027 (0.2% CPU, alive) · KPI §6 (ROL 21:45Z) chưa vi phạm |

## §6 LEVER TỐI ƯU (đề xuất thứ tự — MỖI LẦN 1 BIẾN, theo quy tắc sequential)

| Ưu tiên | Lever | Cơ chế | Chờ điều kiện |
|---|---|---|---|
| 1 | **Mở trần TP** (upside lớn nhất): `MOM_EXIT_POLICY NOW → WAIT/WAITPOS` | Code ĐÃ CÓ SẴN (`tp_plan` + exit TRAIL: lãi ≥1.2 bỏ TP chạy tiếp · ≥2.0 trail đỉnh−0.5) — chỉ 2 dòng config | Replay A/B trước khi bật · Rủi ro: giữ lệnh lâu → pullback |
| 2 | **C7 widen band** loser `[−1.15, −0.45]` → ? | Cứu thêm cặp trước khi −1.2 đẻ rổ (2 slot + BASKET_TIME 15–30′) | **HUMAN chốt thừa số 0.45 hay 0.60** (finding §2) + replay |
| 3 | **R1/R2 nới M0-gate** (0 fill hôm nay) | Thêm lệnh fade stall-top/bottom | Data gốc "10/12 punish trong trend-impulse" → chỉ nới có chọn lọc + replay |
| 4 | **C8 tuning** (1.0→1.25 · −0.90→−1.05) | Theo KPI §6 (TP Δ ≥ −20% · chase=0 · G5 không nuốt lệnh hợp lệ) | **Bắt buộc sau ROL-report tối nay 21:45Z** |
| 5 | Loss-floor (GIỮ NGUYÊN) | PSL_BASKET −6.48 + BASKET_TIME 15/30′ hoạt động đúng (worst-basket live trong cap) | — |

**Discipline**: C8 mới live 3.3h → KHÔNG động thêm lever nào cho đến ROL-report 21:45Z (tránh 2 biến cùng lúc). HUMAN chọn lever → lên plan P2-H4 (research + replay A/B + worktree riêng).

---
*SOT kế tiếp: `docs/P2-H4-*.md` (tạo khi HUMAN chốt lever) · Tài liệu này không động code — report-only.*
