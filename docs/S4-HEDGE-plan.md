# 📋 PLAN: S4-HEDGE — STRUCTURAL HEDGE & PRUNE RECOVERY
> Kho: `/Users/admin/Desktop/DESIGN/XAU_SCALP5` (git, HEAD 454ce71)
> Nguồn: TASK BRIEF S4-HEDGE (14/10) · Đã đối chiếu (audit) với code thực tế trước khi ghi phương án.
> Trạng thái: **Plan mode** — chưa sửa source. L2 Implementation đã được Human (Owner) phê duyệt trong brief.

---

## 🔬 DECONSTRUCT (khối atomic)

| # | Khối | File | Input → Output |
|---|------|------|----------------|
| B1 | Append hằng số S4-HEDGE | `src/config.py` | (append cuối file) → 8 hằng số mới |
| B2 | Máy trạng thái Hedge Basket | `src/scalp_strategy.py` | tick px + open_pos → actions (ENTER/EXIT) |
| B3 | K_CONTEXT chỉ đếm ROOT + HEDGE bypass G2 | `src/scalp_strategy.py` | decide() → gate đúng |
| B4 |腿 HEDGE: không TP broker + gỡ TP ROOT + metadata | `src/scalp_executor.py` | action leg_type=HEDGE → vị thế con |
| B5 | Sửa F1 EXIT_SYNC | `src/scalp_executor.py` | deal history → pnl_est đúng dấu |
| B6 | Truyền metadata rổ + cộng dồn hedge_credit thực | `main.py` | exit("HEDGE_TAKE") → root.hedge_credit |
| B7 | Cập nhật tập nhãn exit reasons + pin | `test_offline.py` | thêm 4 mã → gate pass |
| B8 | Backtest 12 ngày S4 vs Baseline V2 | `_replay_hedge.py` (mới) | DB ro → report PASS/FAIL |
| B9 | Verifier độc lập | `opencode run --agent verifier` | verdict |

---

## 0. QUYỀN L2 + WHITELIST (đã audit)

### 0.1. Whitelist (theo brief) + 1 file phải bổ sung

| File | Phép | Trạng thái audit |
|------|-----|------------------|
| `src/config.py` | append cuối file | ✅ `SPREAD_PTS=0.24`, `LOT=0.02`, `PSL_PTS=3.0`, `K_CONTEXT=4`, `TP_POINTS=1.5`, `FZ_BAND_PTS=0.5` đều khớp số học brief |
| `src/scalp_strategy.py` | máy trạng thái + decide() | ✅ `decide()` tại line 637, check K_CONTEXT tại line 646, PSL tại line 762, `in_rollover` line 429, `_g2_block` line 455 |
| `src/scalp_executor.py` | leg HEDGE + F1 fix | ✅ `enter()` line 115, `sync()` line 78, `modify_position` tồn tại |
| `main.py` | metadata rổ + hedge_credit | ✅ `decide(executor.positions, ...)` line 545, `executor.enter(a, strategy)` line 553 |
| `_replay_hedge.py` | tạo mới (chỉ đọc DB ro) | ✅ mẫu: `_replay_v2.py` đã tồn tại để tham chiếu pattern |
| **`test_offline.py`** | **BỔ SUNG** — brief sửa ở §3.3 nhưng KHÔNG nằm trong whitelist | ⚠️ cần Human xác nhận đưa vào whitelist (xem §5-D1) |
| `STATE.md` | ghi bằng chứng (gate brief bắt buộc) | ✅ implicit qua gate "ghi bằng chứng số học vào STATE.md" |

### 0.2. Denylist (CẤM ĐỤNG)
`.env` · `data/scalp5.db` (chỉ đọc qua `file:data/scalp5.db?mode=ro`) · `src/metaapi_client.py` (hard denylist theo `loop-constraints.md` line 20).

### 0.3. Quy trình (theo `loop-constraints.md` + `AGENTS.md` repo)
- Ghi nhận L2 + whitelist + denylist vào `STATE.md` **trước** khi edit source.
- Kho có git: **tạo branch/worktree `s4-hedge`** (AGENTS.md repo: "Use a git worktree for every code-changing attempt"). Checkpoint commit sau mỗi khối B1..B8 pass gate.
- Restart bot **chỉ** khi 0 vị thế mở hoặc tại ranh giới `ROL 21:45Z`; `py_compile` trước mọi lần chạy.

---

## 1. MATH BẢO VỆ VỐN (khóa — không thay đổi trong implement)

`LOT=0.02 → $2/pt` · `SPREAD_PTS=0.24 → $0.48/lệnh`

| Sự kiện | Công thức | Giá trị |
|---------|-----------|---------|
| Khóa lỗ sớm @ −1.2pt | `(−1.2×2) − (2×0.48)` | **−$3.36 (đóng băng)** |
| Lỗ nếu gỡ sớm + trượt 1.0pt | −3.36 − (1.0×2) | −$5.36 → **cấm gỡ sớm** |
| TRẠNG THÁI `HEDGE_LOCKED` | giá thử thách cản → giữ 1:1 | lỗ giữ −$3.36 |
| Xác nhận A (Stall) | nến M1 tại cản, không phá >1.0pt | giữ/khóa tiếp |
| Xác nhận B (Bounce) | hồi ≥ `0.4pt` về hướng gốc, không IMPULSE | **gỡ chân HEDGE** → `HEDGE_TAKE`, `hedge_credit += realized` |
| `PRUNE_BREAK` (phá cản ≥1.0pt khi đang khóa) | tỉa cả 2 chân | **−$3.36 (±$0.10)** — bằng mức đóng băng |
| `PRUNE_SPAN` (mất biên độ >4.5pt, không có cản) | tỉa cặp khóa | chặn rủi ro vô biên |
| `PRUNE_UNWOUND_BREAK` (đã gỡ, giá phá lại ≥1.0pt) | tỉa ROOT + bù `hedge_credit` | lỗ ròng ≈ **−$3.5..−$5.0** |
| Trần lỗ rổ | PSL cũ: `3.0×2 + 0.48×2` | **−$6.48 (PASS gate 3)** |
| `BASKET_TP` | (floating + credit) ≥ +$0.50 | chốt toàn rổ |

Nguyên tắc: **không bao giờ để rổ lỗ ròng vượt −$6.48** (mức trần PSL cũ).

---

## 2. BƯỚC THỰC THI (B1→B8)

### B1. `src/config.py` — append cuối file
Khối hằng số theo brief §2-Bước1 (8 hằng số: `HEDGE_ENABLE`, `HEDGE_LOCK_PTS=1.2`, `HEDGE_MIN_PROFIT_PTS=1.5`, `HEDGE_BREAK_PTS=1.0`, `HEDGE_BOUNCE_CONFIRM_PTS=0.4`, `HEDGE_MAX_SPAN_PTS=4.5`, `BASKET_TP_USD=0.50`, `HEDGE_ALLOW_SCALE_IN=False`).
> ⚠️ Giá trị khởi tạo `HEDGE_ENABLE` → xem **D1/D2** (§5). Brief ghi `True`; khuyến nghị khởi tạo `False` và flip sau khi PASS gate 3 (tránh đập pin test cũ — xem B7).

### B2. `src/scalp_strategy.py` — máy trạng thái
- Thêm 2 phương thức vào `ScalpStrategy`:
  - `_find_structural_wall(root_side, root_entry, px)`: H-zones (LVL Engine, side="S") / L-zones (side="B") + levels confirmed của S-ladder; chọn cản gần px nhất (code theo brief §2.3 — đã kiểm tra: `self.levels`, `self._safe_zones`, `FZ_BAND_PTS` đều tồn tại).
  - `_manage_hedge_basket(root_pos, open_pos)`: 4 nhánh theo brief —
    (1) `unwound=True` & chưa có hedge → chờ `BASKET_TP` / `PRUNE_BREAK` / PSL fallback;
    (2) NAKED: `pnl_pts ≤ −1.2` → ENTER chân HEDGE + ghi `wall_px`;
    (3) `HEDGE_LOCKED`: 3A phá cản ≥1.0pt → `PRUNE_BREAK` (2 EXIT cùng px), 3B span ≥4.5pt không có cản → `PRUNE_SPAN`, 3C chạm cản + hedge lãi ≥1.5pt + peak + hồi ≥0.4pt + không IMPULSE → `HEDGE_TAKE` (gỡ chân hedge, ghi `hedge_credit`, `unwound=True`);
    (4) không có gì → `[]`.
- Ràng buộc số học kiểm tra lại ở replay (gate 3): `PRUNE_BREAK` khi đang khóa phải dừng lỗ đúng −$3.36 ±$0.10 vì 2 chân vẫn 1:1.

### B3. `src/scalp_strategy.py` — sửa gate trong `decide()` (line 637–…)
- K_CONTEXT: **chỉ đếm ROOT** — `root_positions = [p for p in open_pos if not p.get("parent_id")]` thay cho `len(open_pos)` (hiện tại line 646, 741 dùng `n_open < c.K_CONTEXT`).
- Chân HEDGE **không qua** `_g2_block` (G2-LVL) — chỉ lệnh ROOT mới gate.
- Khi ≥1 rổ ở `HEDGE_LOCKED` hoặc `unwound=True`: **tạm dừng mở ROOT mới cùng chiều đang âm** (chống nhân bản rủi ro).
- Vòng lặp exit: lệnh con (`parent_id` có giá trị) **bỏ qua** TIME_STOP/S_BREAK/DRIFT độc lập — ROOT điều khiển qua `_manage_hedge_basket`.
- ROOT có hedge_leg hoặc `unwound=True` → **skip TIME_STOP** (15') để chờ giá hồi về BASKET_TP.
- TP của ROOT (`pnl_pts ≥ TP_POINTS`) chỉ fire khi `not unwound` và chưa có hedge_leg.
- ROL 21:45Z: ưu tiên số 1, đóng **tất cả** chân (ROOT/HEDGE/SCALE) `reason="ROL"` (giữ nguyên hiện hành).
- `save_state`/`load_state`: lưu + khôi phục metadata rổ (`parent_id`, `leg_type`, `hedge_credit`, `wall_px`, `wall_peak_px`, `unwound`) — tương thích ngược với snapshot cũ (các key mới default None/0.0/False).

### B4. `src/scalp_executor.py` — chân HEDGE trong `enter()` (line 115)
- `leg_type == "HEDGE"`: **không đặt TP broker** (`take_profit=None` trong `create_market_order`).
- **Bypass K_CONTEXT ở executor** (line 120–122 hiện chặn mọi lệnh khi `len(positions) ≥ K_CONTEXT` — brief §2.2 chỉ nói ở strategy; phải sửa cả executor, nếu không chân HEDGE sẽ bị skip): HEDGE leg không đếm/chặn bởi K gate.
- Sau khi fill hợp lệ của chân HEDGE: gọi `await self.client.modify_position(str(parent_id), stop_loss=None, take_profit=None)` để **gỡ TP của ROOT** (tránh sàn tự đóng ROOT giữa lúc khóa). Ký hiệu đã kiểm tra khớp: `modify_position(position_id, stop_loss=None, take_profit=None)` (metaapi_client line 1513). Lỗi → `log.warning`, không throw (khóa vốn vẫn được giữ bằng vị thế mở).
- Append vào `self.positions` dict đầy đủ metadata theo brief §3.1.3 (`parent_id`, `leg_type`, `hedge_credit=0.0`, `unwound=False`, `wall_px`).

### B5. `src/scalp_executor.py` — sửa F1 (EXIT_SYNC ≈ −$3.00) trong `sync()` (line 78)
Hiện tại (line 91–94): vị thế biến mất khỏi broker → ước lượng `pnl_est = TP_POINTS × oz × sign` (≈ +$3.00, chưa trừ spread) rồi append `synced_exits`. Lỗi F1: dấu ước lượng sai trong một số nhánh (brief: EXIT_SYNC ≈ −3.00$). Sửa:
1. Grep "EXIT_SYNC" để xác định đúng điểm ghi nhận (sync + exit_log trong main.py).
2. **Không gán cứng ước lượng**: ưu tiên gọi `client.get_history_deals(from_ts)` (tồn tại, metaapi_client line 1329) filter theo position/ticket, lấy `deal["profit"]` thực.
   > ⚠️ **SAI LẦM CỦA BRIEF**: `client.get_history_deals_by_position(pos_id)` **KHÔNG TỒN TẠI** trong `metaapi_client.py` (denylist — không được thêm). RPC có sẵn: `get_history_deals_by_ticket(ticket_id)` (line 1282) và `get_history_deals(from_ts)` (line 1329). Dùng `get_history_deals` khi RPC `is_synchronized`.
3. Fallback khi chưa lấy được deal history: ước lượng **DƯƠNG** `+(TP_POINTS − SPREAD_PTS) × LOT × 100 = +$2.52` (TP chạm trên sàn), không phải −3.00$.

### B6. `main.py` — metadata rổ + hedge_credit thực
- Khi `executor.enter(a, strategy)` với `a["leg_type"] == "HEDGE"`: không thay đổi gì ở level gọi (metadata nằm trong `a`), nhưng **log** quan hệ parent → con.
- Khi `executor.exit(pos_id, px, reason)` trả về `(pnl_real, ok)`:
  - `reason == "HEDGE_TAKE"` và vị thế đóng là chân con → **cộng dồn thực**: tìm ROOT bằng `parent_id`, cập nhật `root["hedge_credit"] += pnl_real` (thay thế ước tính `hedge_pts × usd_per_pt − spread` do strategy ghi tạm — reconciliation: dùng giá trị thực nếu chênh >$0.05, log warning).
- Giữ chuỗi `save_state` (line 290/536/584) hoạt động với metadata mới (không crash khi snapshot cũ thiếu keys).

### B7. `test_offline.py` — nhãn exit + pin (⚠️ ngoài whitelist brief)
- **SỞ THỰC TẾ: tập nhãn exit nằm ở line 121–122**, không phải line 104 (brief sai vị trí — line 104 là logic PULLBACK):
  ```python
  set(reasons) <= {"TP","TIME","ROL","PSL","DRIFT"}   # line 122
  ```
  → bổ sung thành `{"TP","TIME","ROL","PSL","DRIFT","HEDGE_TAKE","BASKET_TP","PRUNE_BREAK","PRUNE_SPAN"}` (thiếu `PRUNE_UNWOUND_BREAK` — brief §1.1 định nghĩa nhưng §3.3 chỉ liệt kê 4 mã; **kiến nghị thêm** `PRUNE_UNWOUND_BREAK` vào tập, dùng unified reason `PRUNE_BREAK` cho cả 2 nhánh theo mã action của B2 để giữ tập gọn — quyết định D3).
- **PIN SẼ BỊ ĐẬP**: line 123–125 pin `465 ≤ len(ents) ≤ 477` (pin=471). Khi `HEDGE_ENABLE=True` (config default), hành vi entry thay đổi (B3: tạm dừng ROOT âm khi có rổ khóa) → số entry đổi → pin fail. Cách xử lý theo D2:
  - Nếu chạy test với `HEDGE_ENABLE=False` (ns override) → pin 471 giữ nguyên, test tiếp tục bảo vệ baseline.
  - Khi flip `HEDGE_ENABLE=True` → **re-baseline pin mới** (đo `len(ents)` thực, ghi vào STATE.md, cập nhật range pin).

### B8. `_replay_hedge.py` (file mới, chỉ đọc DB)
- Pattern theo `_replay_v2.py` (đã tồn tại): chạy replay 12 ngày trên `file:data/scalp5.db?mode=ro` (KHÔNG mở DB writable).
- 2 chế độ cùng tập lệnh:
  - **Baseline V2**: `HEDGE_ENABLE=False` + `PSL=3.0pt` (giới hạn rổ −$6.48).
  - **S4-HEDGE**: `HEDGE_ENABLE=True`, `HEDGE_LOCK_PTS=1.2`, `HEDGE_BREAK_PTS=1.0`.
- **PASS gate (cả 3 điều):**
  1. Không rổ nào lỗ ròng > −$6.48.
  2. Mỗi `PRUNE_BREAK` (phá cản 1.0pt khi đang khóa): lỗ ròng = −$3.36 ±$0.10.
  3. Tổng PnL 12 ngày S4-HEDGE ≥ tổng PnL Baseline V2.
- Output: `replay_hedge.txt` + bảng per-basket (peak−trough, credit, realized) → dẫn vào STATE.md.

### B9. Verifier độc lập
```bash
opencode run "Verify S4-HEDGE implementation against docs/safety.md and replay_hedge.txt" --agent verifier
```
(Brief ghi `safety.md` — path thực là `docs/safety.md`, đã kiểm tra tồn tại.)

---

## 3. VERIFICATION GATE (tuần tự, bằng chứng ghi vào `STATE.md`)

| Gate | Lệnh | Evidence bắt buộc |
|------|-----|-------------------|
| G1 Syntax | `./.venv/bin/python -m py_compile src/config.py src/scalp_strategy.py src/scalp_executor.py main.py _replay_hedge.py test_offline.py` | "Compiled OK" cho từng file |
| G2 Offline | `./.venv/bin/python _test_state.py && ./.venv/bin/python test_s2.py && ./.venv/bin/python test_offline.py` | snapshot save/load round-trip (metadata mới không crash), S2 pass, off-line pass (theo D2: pin chạy với hedge-off nếu default=False) |
| G3 Replay | `./.venv/bin/python _replay_hedge.py` | 3 điều PASS gate §B8 + số học: min basket loss, danh sách PRUNE_BREAK với pnl mỗi cái, tổng PnL S4 ≥ Baseline |
| G4 Verifier | lệnh B9 | verdict APPROVE + checklist theo `docs/safety.md` |

Mỗi gate fail → tối đa 3 lần fix (luật 3-strike), sau đó dừng + trình bày lựa chọn cho Human.

---

## 4. DEPLOY & RESTART
1. `py_compile` pass → checkpoint commit (worktree `s4-hedge`).
2. **Chỉ restart khi 0 vị thế mở HOẶC tại `ROL 21:45Z`** — kiểm tra `get_positions()` trước khi restart; có vị thế → dời sang ranh giới phiên.
3. Snapshot state (`data/state_snapshot.json`) đã lưu metadata mới (B3) — sau restart, `load_state` phải khôi phục được rổ đang khóa.
4. Post-restart: log đầu tiên phải hiện `[HEDGE]` banner + trạng thái rổ còn sống.

---

## 5. OPEN ITEMS (cần Human chốt trước implement)

### D1 — `test_offline.py` vào whitelist?
Brief §3.3 yêu cầu sửa `test_offline.py` nhưng §0 whitelist không liệt kê file này.
→ **Khuyến nghị: PHÊ DUFM** (thêm vào whitelist, thay đổi: 2 dòng — tập nhãn exit + pin range).

### D2 — Giá trị khởi tạo `HEDGE_ENABLE`
- (a) `False` khởi tạo (khuyến nghị): giữ pin 471 + test cũ nguyên vẹn; flip `True` sau PASS gate 3 + re-baseline pin.
- (b) `True` ngay (theo brief): test_offline đập pin ngay → phải re-baseline cùng commit.
→ **Khuyến nghị: (a)** — flip là 1 dòng config, có revert nhanh nếu replay/realtime bất thường.

### D3 — Tên mã `PRUNE_UNWOUND_BREAK`
Brief §1.1 định nghĩa trạng thái nhưng §3.3 không đưa mã này vào tập exit. Mã action trong code B2 hiện dùng `PRUNE_BREAK` cho cả 2 nhánh (trước và sau unwind).
→ **Khuyến nghị: giữ `PRUNE_BREAK` unified** (cùng cơ học: phá cản ≥1.0pt → tỉa), thêm chú thích log phân biệt nhánh (log `after_unwind=True/False`). Nếu Human muốn phân biệt thống kê → thêm mã `PRUNE_UNWOUND_BREAK` (1 dòng mỗi nơi).

### D4 — Worktree vs branch thường
`AGENTS.md` repo yêu cầu worktree cho mọi code-change; brief whitelist ghi sửa trực tiếp file.
→ **Khuyến nghị: `git worktree add ../XAU_SCALP5-s4-hedge -b s4-hedge`**, implement trong worktree, merge về main sau PASS gate 4.

---

## 6. QUYẾT ĐỊNH ĐÃ CHỐT (14/10 · Human)
- **D2 = (a)**: `HEDGE_ENABLE=False` khởi tạo; flip `True` chỉ sau PASS gate G3 (replay 12 ngày) + re-baseline pin entry.
- **Upload log (14/10 22:xx)**: bundle SẠCH push lên `dactriltd/XAU_SCALP5` (main): `STATE.md`, `loop-run-log.md`, `loop-budget.md` (đã tracked, clean) + 6× `logs/boot_v2*_1014.log` + 4× replay txt + 3× verifier txt + `logs/verify_loop_1014.log` + file plan này. **`logs/scalp5.log` bị LOẠI khỏi bundle** (120 dòng JWT MetaApi thật `token=eyJ...` — chỉ nằm ở bản local, đã xác minh KHÔNG có trong lịch sử git: `git log -S 'token=eyJ'` = 0 commit, HEAD version = 0 dòng).
- D1 / D3 / D4: giữ khuyến nghị (YES / `PRUNE_BREAK` unified / worktree+branch `s4-hedge`) — chốt khi bắt đầu implement.

## 📐 TÓM TẮT 1 ĐOẠN (để giao implementer)
Thêm máy trạng thái 3-level (NAKED → HEDGE_LOCKED → UNWOUND) vào `decide()`: khi ROOT âm 1.2pt mở chân đối ứng không-TP, gỡ TP của ROOT trên broker, giữ khóa 1:1 tại vùng cản cấu trúc; gỡ chân hedge khi cản giữ (hồi ≥0.4pt, không IMPULSE) hoặc tỉa cả rổ khi giá phá cản ≥1.0pt — sàn lỗ cố định −$3.36, trần −$6.48; sửa F1 EXIT_SYNC bằng deal history (fallback +$2.52 dương, không âm); K_CONTEXT chỉ đếm ROOT; restart tại ROL; evidence qua 4 gate (py_compile → offline → replay 12 ngày → verifier).

---

## 7. BẰNG CHỨNG THỰC THI (15/10 · worktree `s4-hedge` · base `16cfd1b`)

> Quy tắc ghi: chỉ ghi số đã đo (LUẬT 3 Empirical). Worktree `../XAU_SCALP5-s4-hedge` (D4),
> bot live PID 7710 chạy nguyên gốc suốt quá trình (zero-downtime ✓ — verify ps 01:31 elapsed).

### 7.1. Audit trước khi code (audit code thật ≠ code trong plan)
| Hạng mục plan | Trạng thái tại base `16cfd1b` |
|---|---|
| main.py: `client.shutdown()` trước `StreamStalled` (WCH/H6) | **ĐÃ CÓ** (main.py L294–299, patch 22:5x 14/10) → không làm lại |
| main.py: SQLite cross-thread fix cho `_lvl` (LVL-THREADING) | **ĐÃ CÓ** (main.py L326–333 boot + L412–417 hook, `sqlite3.connect` sync) → không làm lại |
| `docs/S4-HEDGE-plan.md` §4 B6: "truyền metadata rổ + credit thực" | **CHƯA CÓ** → implement (exit_action sync + re-attach sau adopt) |

### 7.2. Thay đổi đã code (whitelist D1, 7/8 khối)
| File | Thay đổi | Dòng chính |
|---|---|---|
| `src/config.py` | append-only 11 hằng S4-HEDGE (D2: `HEDGE_ENABLE=False`) | cuối file |
| `src/scalp_strategy.py` | `__init__`: registry `hedge_baskets` (persistence snapshot) · `save_state`/`load_state`: `hedge_baskets` (tolerant snapshot cũ) · `_can_open_new_root()` (baseline ≡ `n<K_CONTEXT`; hedge-ON: MAX_ROOT=2 + GAP 20s + STEP 1.0pt + cùng-hướng cần đệm ≥+0.5pts + khóa khi có leg/unwound) · `_find_structural_wall()` (lvl strong_zones + levels + FZ grid, gần giá nhất, None → PRUNE_SPAN) · `_manage_hedge_basket()` (NAKED→LOCKED→UNWOUND: PRUNE_BREAK LOCKED/UNWOUND (D3 branch=), PRUNE_SPAN, HEDGE_TAKE (band cản + leg ≥1.5pts + giật lùi ≥0.4 khỏi wall_peak + không IMPULSE), BASKET_TP net ≥+0.50$, PSL-breaker net ≤−6.48$) · `decide()`: 4 gate root (MOM1 PULLBACK/EDGE×2 + B_SNEO×2 + R1/R2 fill) + vòng EXIT: skip legs (chỉ ROL), managed-root (LOCKED/UNWOUND → skip mọi exit đơn lệnh, miễn TIME), NAKED machine (ENTER leg), prune mirror | quyết định |
| `src/scalp_executor.py` | `enter()`: leg HEDGE không TP broker + gỡ TP root parent sau khớp + metadata 5 trường · `sync()`: F1 fix (deal thật → fallback +$2.52 DƯƠNG · leg anomaly 0.0+warn) | enter L~120, sync L~90 |
| `main.py` | `exit_action()`: sync `hedge_credit` thật (HEDGE_TAKE→root) + log `PRUNE_BREAK (branch=…)` (D3) · entry tlog leg (tp=NULL) + TG 🛡 · re-attach rổ metadata sau adopt+state-load (survive StreamStalled) | exit_action L~120, boot L~350, loop L~560 |
| `test_offline.py` | exit-set + 4 nhãn HEDGE · run_day attach metadata leg (giống executor) | L~40, L~121 |
| `_replay_hedge.py` | MỚI: đối kháng 12 phiên (02/10→14/10) DB ro, A=baseline/B=S4, report `logs/replay_hedge.txt` | file mới |
| `STATE.md` | L2 approval + whitelist + audit NOTE (ghi TRƯỚC khi edit, theo AGENTS.md) | đầu file |

### 7.3. Kết quả 4 Gates (15/10)
| Gate | Lệnh | Kết quả |
|---|---|---|
| 1 Syntax | `py_compile` 6 file | **PASS ✅** |
| 2 Regression (HEDGE_ENABLE=False) | `_test_state` (round-trip OK, có `hedge_baskets`) + `test_s2` 9/9 OK + `test_offline` **ALL PASS** (pin=471 · mix {PSL:93,TP:342,TIME:36} · B pin=19 — 100% khớp V2) | **PASS ✅** |
| 3 Replay 12d | `_replay_hedge.py` → `logs/replay_hedge.txt` | **FAIL ❌ (0/3)** — xem 7.4 |
| 4 Verifier | `opencode run --agent verifier` (review diff + docs + replay) | (chạy sau commit) |

### 7.4. SỔ SỐ GATE 3 (DB `../XAU_SCALP5/data/scalp5.db` ro · TF=1m · 11,650 nến · spread 0.48$)
- **A (Baseline V2, hedge OFF):** 4,886 entries · **+$6,985.97** (TP×3,592 · PSL×1,099 · TIME×195)
- **B (S4-HEDGE+ORCH):** 238 entries · **+$217.66** (BASKET_TP×5 · HEDGE_TAKE×6 · PRUNE_BREAK×84 (42 rổ LOCKED) · TP×113 · PSL×14 · EOD×16) · 56 rổ
- Tiêu chí: (1) worst_basket **−$7.05** ≥ −$6.48 → **FAIL** · (2) PRUNE_LOCKED 42 rổ ≈ −$3.36±0.10: outliers **37/42** (đo −3.44…−6.67$) → **FAIL** · (3) PnL B < A (−$6,768.31) → **FAIL**

### 7.5. CHẨN ĐOÁN (first-principles, không cảm tính)
1. **Gate 3 = FAIL QUYẾT ĐỊNH (không phải proxy m1):** edge của V2 nằm ở VOLUME (4,886 lệnh, TP +$2.52 ×3,592 ≈ +$9k bèo). Orchestrator (MAX_ROOT=2 · không root mới khi rổ active) bóp volume còn 1/20 (+217$) → MỌI hedge "hoàn hảo" cũng không bù được. **Đây là kết quả định lượng của design D1-D4, không phải bug code** (code = đúng spec; regression Gate 2 xanh 100%).
2. **Gate 1/2 = m1-proxy artifact (δ overshoot):** PRUNE_LOCKED lý thuyết −$3.36 là đúng khi leg khớp đúng px=entry+1.2 (LIVE: tick ~1s → δ≤0.2pts → −$3.4…−$3.9). Replay m1 (4 tick/nến) chạm −1.2 tại tick HIGH nến → δ đến ~1.8pts → −$7.05. **LIVE sẽ tốt hơn số replay**, nhưng gate 3 vẫn FAIL → quyết định D2 giữ `HEDGE_ENABLE=False` ĐÚNG.
3. **Fix evidence chạy replay (đã sửa trong session này):** runner ban đầu snapshot rổ tại lúc ROOT đóng (thiếu PnL leg cùng tick) + key leg sai → worst −$88 (sai, chỉ root) → sửa in-place gộp root+legs → −$7.05 (đúng). Bài học: "bằng chứng phải đo đúng thứ cần đo" (LUẬT 3).

### 7.6. QUYẾT ĐỊNH THEO PLAN + BÀN GIAO
- **D2: GIỮ `HEDGE_ENABLE=False`** (Gate 3 FAIL 0/3) → KHÔNG flip, KHÔNG re-baseline pin test_offline (chế độ hedge-ON chưa được nghiệm thu).
- **MERGE: CHƯA đủ điều kiện** (plan Phase 4 yêu cầu 4/4 Gates + verifier APPROVE). Branch `s4-hedge` commit code + bằng chứng, **chờ Human quyết định phương án** (xem §8).

## 8. PHƯƠNG ÁN CHO HUMAN (sau Gate 3 FAIL)
| # | Phương án | Nội dung | Trade-off |
|---|---|---|---|
| P1 | **Ship subset "an-toàn-hóa" (khuyến nghị xét trước)** | Merge CHỈ: fix F1 EXIT_SYNC + tlog/tg leg-ready code (mặc định tắt) — hedge logic nằm sau flag `HEDGE_ENABLE=False` → merge không đổi hành vi bot live (Gate 2 đã chứng minh 100% parity), giữ sẵn code để bật khi đủ điều kiện | Zero rủi ro live (flag off) · nhưng không "mở" được S4 |
| P2 | **Tune lại orchestrator + re-gate** | nới MAX_ROOT_POSITIONS (2→4/∞) · giảm MIN_ROOT_GAP_SEC · giữ hedge LOCK (đo riêng "chỉ hedge, không bóp volume") — chạy lại `_replay_hedge.py` (cập nhật theo tham số) | Cần thêm 1 cycle replay + verifier · có thể Gate 3 vẫn FAIL (volume là vấn đề gốc) |
| P3 | **Giữ branch, đóng S4-HEDGE** | Chỉ commit + bằng chứng; S4 chuyển BACKLOG (STATE.md) | An toàn nhất · S4 không được triển khai |

## 9. P2-Tuned CYCLE (15/10 00:5x, HUMAN duyệt Q1-Q4: P2+P1 · LIVE-ngay-khi-PASS)
**Tham số đã apply (branch `s4-hedge`)**: K_CONTEXT 4→8 · MAX_ROOT_POSITIONS 2→4 · MIN_ROOT_STEP_PTS 0.35 · MIN_ROOT_GAP_SEC 5 · +HEDGE_TIMEOUT_MIN 30 · +BASKET_TIME_MAX_LOSS_USD 1.50 · +BASKET_TP_TRIGGER_USD 1.20 · per-position hedge (gỡ khóa toàn cục + bỏ +0.5pts) · BASKET_TIME (LOCKED+UNWOUND) · UNWIND_BREAKEVEN_GUARD (net_peak_usd persistence).
**Gates**: G1 ✓ · G2 hedge-ON pin=82 (58 v0 + 24 legs · v0-signal 0/58) + hedge-OFF pin=493 (K=8) · test_s2 9/9 · state-rt ✓ · **G3 FAIL 0/3 (lần 2)**: worst_basket **−$10.36** · **184/201** PRUNE_LOCKED outliers · PnL B **+$561.07** < A +$6,985.97 (volume B 238→**1,104** entries nhưng hedge PnL-âm: 402 PRUNE vs 39 HEDGE_TAKE).
**Chẩn đoán**: (1) NAKED/LOCKED **không có PSL breaker** (cầu chì −$6.48 chỉ ở UNWOUND) → tail không trần → −$10.36 · (2) BASKET_TIME floor −$1.50 → rổ lỗ sâu không release, chôn thêm · (3) PnL gap = volume suppress + chi phí PRUNE.
**Quyết định**: PARK D2-safe — `HEDGE_ENABLE=False` (branch), replay A PIN K_CONTEXT=4 (module K=8 không kéo theo baseline) · KHÔNG merge/restart · options mới **O1/O2/O3** → `S4-HEDGE-DECISIONS.md` (v2).
