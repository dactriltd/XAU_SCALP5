# 🔬 XAU_SCALP5 — 5-MINUTE VERIFICATION LOOP
## Checklist theo Karpathy's Laws · 5 Whys · 5W2H

> **Mục đích**: Mỗi 5 phút, bot được "xét hỏi" 5 khối atomic. Mỗi khối = 1 câu hỏi
> với bằng chứng thực thi (Karpathy Law 3) + chuỗi 5 Whys + 7 W2H.
> Kết quả: JSON report + exit code (0=PASS, 1=WARN, 2=FAIL) cho supervisor/alerting.

---

## 🧱 7 BLOCKS ATOMIC (Karpathy Law 7: Deconstruct First)

| Block | Layer | Data Source | Threshold | Status |
|-------|-------|-------------|-----------|--------|
| **1** | I/O — Tick Stream | `logs/scalp5.status.json` → `ts` | `age > 300s` = FAIL | ✅/⚠️/❌ |
| **2** | CPU — Strategy State | `status.json` → `drift5m, mode, L[], H[]` | `\|drift\| > 20` = WARN | ✅/⚠️/❌ |
| **3** | EXEC — Positions | `status.json` → `open[], day_loss, halted` | `n_open > 4` = FAIL | ✅/⚠️/❌ |
| **4** | DATA — Telemetry | `data/scalp5.db` → `entry_log, exit_log` | `no rows today` = WARN | ✅/⚠️/❌ |
| **5** | SUPERVISOR — Watchdog | `logs/scalp5.log` + `scalp5.pid` | `stalled ≥ 3` = FAIL | ✅/⚠️/❌ |
| **6** | TRADE — Entry Quality | `data/scalp5.db` → JOIN entry+exit | `win_rate < 40%` = WARN · `streak_loss ≥ 3` = FAIL | ✅/⚠️/❌ |
| **7** | STRUCTURE — Resistance | `status.json` → `px, L[], H[]` | `in_zone = True` = WARN · `box < 2.0` = WARN | ✅/⚠️/❌ |

> **Blocks 1-5** = system health (bot còn sống không?)  
> **Blocks 6-7** = trading quality (trade tốt không? Cấu trúc đang ở đâu?)

---

## 🔷 BLOCK 1: TICK STREAM (I/O Layer)

### Câu hỏi chủ đạo (What)
> *"Bot có đang nhận tick live không? Tick cuối cách giờ vài giây?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | Tick freshness: `now - status.json.ts` |
| **Why** | Tick chết im lặng → `strategy.now_ts` không cập nhật → `decide()` bị gate → bot ngồi im (failure mode nguy hiểm nhất: không báo lỗi, không crash) |
| **Where** | `logs/scalp5.status.json` (viết mỗi 5 min bởi main.py heartbeat) |
| **When** | Mỗi chu kỳ verify (5 min) |
| **Who** | `TickCollector` (ghi) · `main.py watchdog` (đọc) · verify loop (kiểm tra) |
| **How** | Đọc `ts` từ status.json, tính `age = time.time() - ts` |
| **How much** | `age ≤ 300s` = PASS · `age > 300s` = FAIL (TICK_STALE_SECONDS) · `age > 120s` = WARN |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 0** (First Principles) | Tick = `on_symbol_price_updated()` callback từ WebSocket MetaAPI. Nguyên tử: 1 tick = 1 price update. Không tick = WebSocket chết hoặc listener không attach. |
| **Law 1** (Minimal) | Chỉ cần đọc 1 file JSON, 1 field `ts` — không cần connect broker. |
| **Law 2** (System 2) | Before kết luận "tick OK", phải kiểm tra: `ts` có hợp lệ không (không phải 0)? `px` có nằm trong range XAUUSDm hiện tại? |
| **Law 3** (Empirical) | Bằng chứng: `ts=1791908508, now=1791908520, age=12s, px=4157.286` — concrete, không phải "có vẻ ổn" |
| **Law 5** (CPU vs I/O) | I/O: đọc status.json. CPU: so sánh timestamp. Không gọi RPC broker. |
| **Law 9** (Baseline) | Baseline: tick mỗi 1-2s (XAUUSDm live). `age ≤ 120s` = still alive. `age > 300s` = WebSocket definitely dead. |

### 5 Whys — Failure Mode: "Bot không trade"

```
Q1: Why bot không trade?
    → strategy.now_ts chưa cập nhật → decide() bị gate (line 222 main.py)
Q2: Why now_ts không cập nhật?
    → on_tick_callback không được gọi → TickCollector không nhận tick
Q3: Why TickCollector không nhận tick?
    → WebSocket MetaAPI chết im lặng (2 sự cố 16:48/16:52 Hanoi 13-10)
Q4: Why WebSocket chết im lặng?
    → MetaAPI cloud gateway có issue: synchronizationStatus=None dù
      connectedToBroker=True (local terminal state rỗng)
Q5: ROOT CAUSE:
    → Không có supervisor với backoff ở tầng gateway.
      Solution hiện tại: TICK_STALE_SECONDS watchdog (main.py line 214)
      + StreamStalled exception + main() backoff (30→60→120→300s).
      Verification: check logs/scalp5.log có "STREAM STALLED" không.
```

### Sanity Check (Karpathy Law 8)

```python
# Chạy trước khi verify: status.json có tồn tại không?
import json, time, os
path = "logs/scalp5.status.json"
if not os.path.exists(path):
    print("FAIL: status.json not found → main.py heartbeat chưa chạy")
    exit(2)
data = json.load(open(path))
age = time.time() - data["ts"]
assert data.get("px") is not None, f"FAIL: px=None (no tick yet)"
assert age < 300, f"FAIL: tick age={age:.0f}s > 300s"
print(f"PASS: age={age:.0f}s, px={data['px']}")
```

---

## 🔷 BLOCK 2: STRATEGY STATE (CPU Layer)

### Câu hỏi chủ đạo (What)
> *"drift5m, S-ladder, mode đang ở trạng thái hợp lý không?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | `drift5m`, `mode`, số level L/H confirmed & chưa broken |
| **Why** | Strategy state drift → quyết định entry/exit sai (S-ladder rỗng = B_SNEO không fire; drift cực đoan = MOM1 có thể bị noise) |
| **Where** | `status.json` → `drift5m, mode, L[], H[]` (mỗi item: `[px, touches, confirmed]`) |
| **When** | Mỗi chu kỳ 5 min |
| **Who** | `ScalpStrategy` (bảo trì) · verify loop (đọc) |
| **How** | So sánh `drift5m` với range ±$20; đếm `L[] + H[] > 0` (S-ladder còn sống) |
| **How much** | `L+H = 0` = WARN (S-ladder rỗng) · `\|drift5m\| > 20` = WARN (extreme) · `mode` hợp lệ (None/BUY/SELL) = PASS |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 0** | S-ladder = fractal ±2 M1 candles. Confirm = giá hồi ≥$0.5 khỏi S OR 1' trôi qua. Không cần tương lai (không hindsight). |
| **Law 2** | Before "S-ladder OK": kiểm tra mỗi level `confirmed=True AND NOT broken`. Level có `touches` hợp lệ (0-2)? |
| **Law 3** | Bằng chứng: `L=1 (4156.657, touches=0, confirmed=True)`, `H=8 levels` — concrete numbers |
| **Law 9** | Baseline: trong 1 phiên XAUUSDm, S-ladder M1 nên có ≥ 2-3 L + ≥ 2-3 H confirmed. Rỗng = bot vừa start hoặc S-chưa-confirmed. |

### 5 Whys — Failure Mode: "S-ladder rỗng, không có entry"

```
Q1: Why S-ladder rỗng?
    → Tất cả level đã broken (price xuyên qua) hoặc chưa confirmed
Q2: Why level broken?
    → Price moved > S_CHAIN_BREAK ($0.1 M1) qua tất cả H/L zones
Q3: Why price moved qua tất cả?
    → Strong trend (M1 momentum ≥ $1.5/3 bars) — break structure
Q4: Why strong trend?
    → News event / session shift (London/NY open) / M1 data chưa đủ warmup
Q5: ROOT CAUSE:
    → Warmup không đủ nến M1 trong ngày (bot start giữa phiên → seed_m1_bars
      chỉ có N nến → S-ladder chưa build hết).
      Fix: WARMUP log trong main.py line 154-159 cho biết n_seed và L/H-alive.
      Verify: check `[WARMUP]` line trong log — nếu n_seed=0 → seed fail.
```

---

## 🔷 BLOCK 3: POSITIONS (EXECUTOR Layer)

### Câu hỏi chủ đạo (What)
> *"Có bao nhiêu vị thế mở? Day-loss có vượt cap không? Halted đúng không?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | `n_open`, `day_loss`, `halted` từ status.json; TP của từng vị thế |
| **Why** | Vị thế mồ côi (TP không ở broker) = rủi ro tài chính; day_loss vượt cap mà không halted = bug executor |
| **Where** | `status.json` → `open[]` (list: `{id, side, entry, entry_ts, anchor}`) |
| **When** | Mỗi chu kỳ 5 min |
| **Who** | `ScalpExecutor` (quản lý) · verify loop (đọc) |
| **How** | `n_open ≤ K_CONTEXT (4)`, `day_loss ≥ -30` OR `halted=True`, mỗi vị thế có `entry_ts` hợp lệ |
| **How much** | `n_open > 4` = FAIL (K violation) · `day_loss < -30 AND NOT halted` = FAIL (cap breach) |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 0** | 1 vị thế = 1 broker MT5 ticket. TP nằm ở broker (không phải trong bot). Restart bot không mất TP. |
| **Law 3** | Bằng chứng: `open=[{id: '12345', side: 'L', entry: 4157.2, entry_ts: 1791908000}]` — concrete |
| **Law 9** | Baseline: 0-4 vị thế mở (K=4). day_loss ∈ [-30, +∞]. Halted=False khi day_loss > -30. |

### 5 Whys — Failure Mode: "Day-loss vượt cap nhưng bot vẫn entry"

```
Q1: Why bot vẫn entry khi day_loss < -30?
    → executor.halted chưa được set True
Q2: Why halted chưa set?
    → at_daily_cap property trả về False (day_loss chưa cập nhật)
Q3: Why day_loss chưa cập nhật?
    → note_closed() chưa được gọi cho vị thế vừa đóng
Q4: Why note_closed chưa gọi?
    → Executor.exit() bị except trước khi note_closed (RPC failure)
Q5: ROOT CAUSE:
    → exit() có try/except không wrap note_closed → PnL không accumulate.
      Fix: kiểm tra exit_log trong DB — nếu có exit nhưng day_loss không đổi
      → bug note_closed. Verify: SELECT COUNT(*) FROM exit_log WHERE ts > today_start
```

---

## 🔷 BLOCK 4: TELEMETRY (DATA Layer)

### Câu hỏi chủ đạo (What)
> *"Có entry/exit log trong DB không? PnL thực tế bao nhiêu?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | Số row `entry_log`, `exit_log` trong `data/scalp5.db`; PnL tổng hợp hôm nay |
| **Why** | Không có telemetry → không audit trail → không trace PnL (Karpathy Law 3: "mọi khẳng định phải có bằng chứng thực thi") |
| **Where** | `data/scalp5.db` → `entry_log(ts, pos_id, kind, entry, tp, anchor, touch, drift5m)` |
| **When** | Mỗi chu kỳ 5 min (check `MAX(ts)` của cả 2 bảng) |
| **Who** | `main.py tlog()` (ghi) · verify loop (đọc) |
| **How** | `sqlite3` query: `SELECT COUNT(*), MAX(ts) FROM entry_log` + `exit_log` |
| **How much** | `n_entries + n_exits = 0` trong ngày = WARN (bot idle?) · `last_ts > 1h` = WARN |

### 5 Whys — Failure Mode: "exit_log có row nhưng PnL=0 (TP_BROKER estimate sai)"

```
Q1: Why PnL=0 trong exit_log?
    → exit_log.gia là exit_px (sai) hoặc pnl field null
Q2: Why pnl null?
    → executor.exit() không đọc được profit từ broker (RPC fail)
Q3: Why RPC fail?
    → rpc_connection closed (MetaAPI RPC disconnected)
Q4: Why RPC closed?
    → Gateway timeout / account không connected
Q5: ROOT CAUSE:
    → _reconnect_rpc chưa được gọi (preflight error không trigger).
      Fix: check log có "RPC closed -> reconnecting once" không.
      Nếu có nhưng vẫn fail → MetaAPI account bị disconnect hoàn toàn.
```

---

## 🔷 BLOCK 5: SUPERVISOR (WATCHDOG Layer)

### Câu hỏi chủ đạo (What)
> *"StreamStalled có xảy ra không? Backoff đang ở mức nào? Bot process còn sống không?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | Số lần `STREAM STALLED` trong log gần nhất; PID process còn valid không |
| **Why** | Supervisor không hoạt động → WS stall tiếp theo = bot chết hẳn (không tự restart) |
| **Where** | `logs/scalp5.log` (last 50 lines) · `logs/scalp5.pid` |
| **When** | Mỗi chu kỳ 5 min |
| **Who** | `main.py supervisor loop` (quản lý) · verify loop (đọc) |
| **How** | `grep -c "STREAM STALLED" logs/scalp5.log \| tail -50` + `kill -0 $(cat logs/scalp5.pid)` |
| **How much** | `stalled_count ≥ 3` trong session = FAIL (supervisor weak) · PID dead = FAIL |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 6** (Agentic Loop) | Supervisor = `main()` while-loop. Mỗi `StreamStalled` = 1 Plan→Act→Observe→Reflect cycle. Backoff = Reflect điều chỉnh (kéo dài thời gian chờ). |
| **Law 7** (Deconstruct) | Atomic blocks: (1) PID alive? (2) log có StreamStalled? (3) backoff đúng exponential? |
| **Law 9** (Baseline) | Baseline: 0 StreamStalled trong 1 session bình thường. Nếu có, backoff 30→60→120→300s (max 300s, không tăng vô hạn). |

### 5 Whys — Failure Mode: "Bot chết hẳn, không tự restart"

```
Q1: Why bot chết hẳn?
    → SystemExit(3) cũ khi start_streaming fail (đã fix 13-10 22:xx)
Q2: Why StreamStalled không trigger?
    → TICK_STALE_SECONDS watchdog chỉ chạy khi strategy.now_ts đã set (≥ 1 tick)
    → Nếu stream chết TRƯỚC tick đầu tiên → watchdog không hoạt động
Q3: Why watchdog không hoạt động trước tick đầu?
    → watch_base = 0 → time.time() - 0 rất lớn → watchdog trigger ngay (bug? hay feature?)
Q4: Why trigger ngay?
    → Actually: watch_base được set ở line 199 main.py = int(time.time()) → OK
    → Nhưng nếu stream stall khi now_ts=0 → watchdog chưa kích hoạt (continue at line 222)
Q5: ROOT CAUSE:
    → Gap: watchdog chỉ active khi now_ts ≠ 0. Pre-tick stall = không có watchdog.
      Fix: cần "boot watchdog" riêng (time.time() - last_boot_ts > BOOT_STALE_S).
      Verify: check log có "stream_connection READY" không trước tick đầu.
```

---

## 🔷 BLOCK 6: ENTRY QUALITY (TRADE LAYER)

### Câu hỏi chủ đạo (What)
> *"Chất lượng điểm vào lệnh đang ở mức nào? Win rate, TP rate, drift alignment?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | win_rate, TP_rate, TIME_rate, against-drift%, streak_loss, PnL today (DB) |
| **Why** | Entry quality low → PnL âm, strategy cần tuning (MOM_PUB_PTS, FZ_FADE) |
| **Where** | `data/scalp5.db` → JOIN `entry_log` + `exit_log` (exit_log = bot-initiated exits only) |
| **When** | Mỗi chu kỳ 5 min (cập nhật khi có exit mới) |
| **Who** | `main.py tlog()` (ghi) · verify loop (đọc + tính metrics) |
| **How** | `sqlite3` query → tính: win rate, % TP exits, % against-drift entries, loss streak |
| **How much** | `win_rate < 40%` = WARN · `streak_loss ≥ 3` = FAIL · `TP_rate < 25%` = WARN |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 0** | 1 lệnh = entry_px → (TP\|TIME\|ROL) → exit_px → PnL. Không hindsight (exit_log đã có ts cụ thể). |
| **Law 3** | Bằng chứng: `entries=11, closed=4, wins=3, losses=1, win_rate=75%, TP=75%, against-drift=18%` — concrete |
| **Law 9** | Baseline (13-10): 11 entries, 3 TP + 1 S_BREAK. TP rate 75% = tốt. against-drift 18% = thấp (vào WITH momentum) → cần tuning |

### 5 Whys — Failure Mode: "Nhiều lệnh TIME exit, PnL âm"

```
Q1: Why nhiều TIME exits?
    → Giá không chạy ≥ 1.5pts trong MOM_TIME_STOP (10m)
Q2: Why giá không chạy?
    → Entry vào WITH momentum (đuổi giá) — giá đã chạy rồi, vào muộn
Q3: Why WITH momentum?
    → MOM_PUB_PTS (0.8) chưa đủ deep để chờ dip; arm fire khi px chạm giá arm
      nhưng giá vẫn đang chạy lên → entry đuổi theo
Q4: Why FZ_FADE chưa hiệu quả?
    → FZ_FADE chỉ flip khi nến tín hiệu CHẠM H-zone/L-zone (touches ≥ 2).
      Nếu strong zones chưa build (touches=0) → FZ_FADE không active
Q5: ROOT: cần tăng FZ_MIN_TOUCH=1 (chỉ cần 1 lần test) hoặc
      thêm FZ zone từ M5 swings (không chỉ M1). Check block 7 trước.
```

### LƯU Ý QUAN TRỌNG
> **exit_log CHƯA có TP-broker fills** (TP-filled positions chỉ đi qua `note_closed() → day_loss`,
> không ghi vào `exit_log`). → `n_tp_broker_est` là ước tính (total_entries - closed_db),
> **không phải empirical PnL**. Block 6 đánh giá quality trên bot-initiated exits.

---

## 🔷 BLOCK 7: STRUCTURE AT RESISTANCE/SUPPORT (STRUCTURE LAYER)

### Câu hỏi chủ đạo (What)
> *"Giá đang ở đâu so với các mức cản mạnh? Có trong 'box' không?"*

### 5W2H

| Câu hỏi | Trả lời |
|---------|---------|
| **What** | strong_L/H (touches≥2), price proximity (±0.5pts), box range, structure density |
| **Why** | Tại điểm cản mạnh → biến động cao, FZ_FADE nên active; box hẹp → MOM1 ít hiệu quả |
| **Where** | `status.json` → `px, L[], H[]` (mỗi item: `[px, touches, confirmed]`) |
| **When** | Mỗi chu kỳ 5 min |
| **Who** | `ScalpStrategy._maintain_levels()` (bảo trì) · verify loop (đọc) |
| **How** | Lọc strong levels (confirmed ∧ touches≥2); so px vs nearest strong H/L |
| **How much** | `in_zone=True` = WARN (high variance, caution) · `box < 2.0` = WARN (range-bound) |

### Karpathy Laws áp dụng

| Law | Câu hỏi self-check |
|-----|-------------------|
| **Law 0** | "Cản mạnh" = mức giá đã được 2+ nến M1 test (fractal ±2 confirm). Không cần dữ liệu tương lai — touches đếm từ quá khứ. |
| **Law 10** | *"Cản mạnh giống như chốt cửa: càng nhiều người thử mở (touches) → càng khó phá (break prob thấp) và càng dễ bật lại (bounce prob cao). Box range hẹp = hành lang, giá đi như bi trong ống."* |
| **Law 5** | I/O: đọc status.json (~500B). CPU: so px vs levels (O(n), n≤8). Không gọi broker. |
| **Law 9** | Baseline: phiên XAUUSDm bình thường → 3-5 H + 3-5 L confirmed. strong zones (touches≥2) = 1-3 mức. |

### 5 Whys — Failure Mode: "Giá kẹt trong box, MOM1 không fire"

```
Q1: Why giá kẹt?
    → Price giữa 2 strong levels (strong_L + strong_H), range hẹp
Q2: Why range hẹp?
    → MOM1 cần net3 ≥ 1.5pts để fire; nếu box < 3pts → net3 thường < threshold
Q3: Why box hẹp?
    → Strong H/L hình thành từ nhiều nến M1 test cùng vùng (FZ grid 0.25pts)
Q4: Why strong H/L chưa break?
    → Trend yếu / range-bound session (Asian, London pre-open)
Q5: ROOT: MOM1 designed cho impulse (PULLBACK entry). Khi range-bound,
      → chuyển mode B_SNEO (S-ladder trigger) hoặc chờ breakout box.
      Verify: box_size_pts < 2.0 → WARN "MOM1 underperform expected".
```

### Assessment logic (Block 7)

```
If strong_h AND strong_l exist:
    box_size = max(strong_h) - min(strong_l)
    if box_size < 2.0 → "tight box, range-bound, MOM1 yếu" (WARN)

If px within ±0.5pts of strong_h:
    → "price at RESISTANCE — FZ_FADE: LONG signals flip to SHORT" (WARN)
If px within ±0.5pts of strong_l:
    → "price at SUPPORT — FZ_FADE: SHORT signals flip to LONG" (WARN)

If no strong levels (all touches=0):
    → "S-ladder fresh/rebuilding — chưa có strong zones" (PASS, không WARN)
```

---

## 📊 TỔNG HỢP: VERIFY CYCLE (5 MIN)

### Kết quả output (Karpathy Law 10: Pedagogical)

```json
{
  "ts": 1791908508,
  "overall": "PASS",
  "n_fail": 0,
  "n_warn": 0,
  "checks": [
    {"block": "1_TICK_STREAM",          "status": "PASS", "observed": "age=12s, px=4157.286"},
    {"block": "2_STRATEGY_STATE",       "status": "PASS", "observed": "drift=-1.80, mode=None, L=1 H=8"},
    {"block": "3_POSITIONS",            "status": "PASS", "observed": "open=0, day_loss=0.00, halted=False"},
    {"block": "4_TELEMETRY",            "status": "PASS", "observed": "entries=12, exits=11, last=142s ago"},
    {"block": "5_SUPERVISOR",           "status": "PASS", "observed": "pid_alive=True, stalled=0"},
    {"block": "6_ENTRY_QUALITY",        "status": "PASS", "observed": "win_rate=75%, TP=75%, against-drift=18%, streak=0"},
    {"block": "7_STRUCTURE_RESISTANCE", "status": "PASS", "observed": "px=4157, strong_L=1 strong_H=0, box=N/A, in_zone=False"}
  ]
}

### Exit code (cho cron/alerting)

| Code | Ý nghĩa | Hành động |
|------|---------|-----------|
| **0** | PASS — tất cả blocks OK | Không làm gì |
| **1** | WARN — có block cảnh báo | Log + notify Telegram |
| **2** | FAIL — có block nghiêm trọng | Alert + kiểm tra thủ công / restart bot |

---

## 🚀 CÁCH CHẠY

### Chạy 1 lần (manual check)
```bash
cd XAU_SCALP5
./.venv/bin/python scalp5_verify.py --once
# exit code: 0=PASS 1=WARN 2=FAIL
cat logs/scalp5_verify_report.json
```

### Chạy liên tục (5 min/cycle)
```bash
cd XAU_SCALP5
nohup ./.venv/bin/python scalp5_verify.py --loop >> logs/verify5.out 2>&1 &
```

### Cron (hàng 5 phút, không cần --loop)
```bash
*/5 * * * * cd /path/XAU_SCALP5 && ./.venv/bin/python scalp5_verify.py --once >> logs/verify5.out 2>&1
```

---

## 📋 CHECKLIST TÓNG KẾT (Quick Reference)

Mỗi 5 phút, tự hỏi 7 câu hỏi:

```
SYSTEM HEALTH:
[1] TICK:    now - status.ts ≤ 300s?               (I/O alive?)
[2] STRAT:   L+H > 0 AND |drift| ≤ 20?            (CPU sane?)
[3] POS:     n_open ≤ 4 AND day_loss OK?           (EXEC safe?)
[4] DATA:    entry_log + exit_log có rows?          (AUDIT trail?)
[5] SUPER:   PID alive AND stalled < 3?            (RECOVER capable?)

TRADING QUALITY:
[6] ENTRY:   win_rate ≥ 40% AND streak_loss < 3?   (TRADE quality?)
[7] STRUCT:  in_zone=False OR box ≥ 2.0?           (STRUCTURE favorable?)
```

Tất cả PASS → ✅ bot khỏe + trade tốt.
Có WARN → ⚠️ monitor, xem block nào WARN + 5 Whys tương ứng.
Có FAIL → ❌ can thiệp: check log, xem 5 Whys, restart/tuning nếu cần.
