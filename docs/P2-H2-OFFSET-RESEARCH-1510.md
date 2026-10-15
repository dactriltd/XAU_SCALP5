# P2-H2 RESEARCH — Tách Log Theo Ngày UTC + Kiểm Định CROSS_OFFSET/PINGPONG + Orphan-Check Live
> 15/10 09:0x+07 · L1 read-only (chưa code) · base: P2-H deployed (code @ 3dbf62f, PID 88090)

## 0. Kết Luận Nhanh
| Hạng mục | Verdict |
|---|---|
| Log-split `YYYY-MM-DD_scalp5.log` (UTC) | ✅ KHẢ THI, ~30 dòng, deploy kèm restart kế tiếp; UTC boundary = M2 day$ + exit_log ts (1:1) |
| PINGPONG (2 nhịp + stop ±0.25pts) | ❌ **TỪ CHỐI** — stop 0.25pts < M3 gate 0.35pts < burst-span quan sát 0.43pts → false-trip noise; redundant với PSL_BASKET −6.48 |
| CROSS_OFFSET — phần BASKET-OFFSET (winner giải phóng rổ LOCKED) | ⏸ DEfer — RECOVERY đã xử lý rổ trong 1.3–2.1′ (hôm nay 3/3 rổ PRUNE_RECOVERY); chỉ có giá trị ngày root adverse |
| CROSS_OFFSET — phần **PRE-LOCK RESCUE** (winner ≥+0.9 cứu naked-loser −0.5..−1.15 trước khi đẻ hedge) | ✅ **CHẤP nhận là C7** — component duy nhất P2-H không cover |
| Orphan-check live 09:04 | ✅ SẠCH — 0 open; 3 X1-ghost lặp lại (noise-only, exit_log SẠCH, verify §2) |

---

## 1. Tách Log Theo Ngày UTC — Thiết Kế

### 1.1 Hiện trạng (evidence)
- `main.py` L63-68: `basicConfig(StreamHandler + FileHandler("logs/scalp5.log"))` — 1 file duy nhất, trộn mọi ngày.
- nohup stdout → `logs/scalp5.out` (SDK MetaApi tự ghi log riêng ra stdout — không qua `logging`).
- Kích thước 09:04: `scalp5.log` = **24MB** (10/03→10/15, ~2MB/ngày) · `scalp5.out` = 5.1MB (từ 08:40).
- Incident lịch sử: 4.5GB/2h `.out` (13/10) đã được chặn bằng `setLevel(WARNING)` cho SDK loggers (L72-74) — nhưng SDK vẫn write stdout trực tiếp → `.out` tiếp tục phình chậm.

### 1.2 Design đề xuất (`DailyUTCFileHandler`)
```python
# ~25 dòng, chỉ stdlib (logging.handlers)
class DailyUTCFileHandler(logging.FileHandler):
    def __init__(self, pattern):  # pattern = "logs/%Y-%m-%d_scalp5.log"
        self.pattern = pattern; self._date = None
        super().__init__(self._filename_for(datetime.datetime.now(timezone.utc)))
    def _filename_for(self, dt): return self.pattern % dt
    def emit(self, record):
        d = datetime.datetime.fromtimestamp(record.created, tz=timezone.utc).date()
        if d != self._date:  # qua ngày UTC → đóng file cũ, mở file mới (in-process)
            self.close(); self._date = d
            self.baseFilename = self._filename_for(d); self.stream = self._open()
        super().emit(record)
```
- **UTC, không phải +07** (luận chứng quyết định): M2 restore day$ (main.py L336) SUM `exit_log` theo **UTC-day** (`ts >= 07:00 local`); mọi `ts` trong DB = unix UTC → file log 1 ngày = đúng 1 ngày kế toán PnL (check DAILY cap chỉ đọc 1 file). Chia theo +07 sẽ xé 1 ngày giao dịch ra 2 file (07:00–24:00 vs 00:00–07:00 local).
- Rotation = in-process khi qua 00:00Z (log tiếp theo) → **zero downtime** sau khi deploy.
- Retention: self-cleanup lúc boot (xoá `*_scalp5.log` >14 ngày, ~5 dòng main.py) — không cần cron/launchd (LUẬT 1: tránh dependency vận hành).
- `.out`: boot line kế tiếp đổi `>> logs/$(date -u +%F)_scalp5.out` (hoặc `>/dev/null` — structured log đã đủ ở `.log`).
- **Không dùng `TimedRotatingFileHandler`**: chỉ support timezone local, filename sai định dạng `*_scalp5.log`.
- Deploy: cần 1 lần restart (gập chung cycle vá, không riêng lẻ).

### 1.3 LAW-1 check
25 dòng stdlib, no-dependency ✓; 1 custom class (1 cấp trừu tượng) ✓.

---

## 2. Orphan-Check Live (09:04+07)

### 2.1 Hiện tại
- Broker `positions` table = **0 open** (query trực tiếp DB) → không có orphan nào lúc này.
- Cluster 08:44–08:59 (12 lệnh mở → 12 exit, **1:1 sạch**):
  | Rổ | Root | Leg (HEDGE) | Đóng bằng | Net rổ | Thời gian giữ slot |
  |---|---|---|---|---|---|
  | #1 | L 4877144381 +2.03 | S 4877148810 (ORPHAN tick-đầu −4.06) | PRUNE_RECOVERY + ORPHAN | −2.03 | 08:44:38→08:45:58 = **1.3′** |
  | #2 | L 4877143589 +2.04 | S 4877148646 −4.97 | PRUNE_RECOVERY | −2.93 | 08:44:03→08:45:58 ≈ **2.1′** |
  | #3 | L 4877162872 +2.35 | S 4877165304 −4.38 | PRUNE_RECOVERY | −2.03 | 08:47:15→08:50:11 = **3.0′** |
  - TP solo: 4877151711 +3.00 · 4877157192 +2.84 · 4877197160 +3.00 · 4877213079 +2.76 (TP 1.5pts = +3.00$ đúng $2/pt ✓)

### 2.2 X1 ghost — xác nhận LẶP LẠI ×3 (từ sau restart)
- 4877148646 @08:46:04 · 4877157676 @08:49:18 · 4877165304 @08:50:15: sau PRUNE_RECOVERY pair-close, sync() re-add leg (broker close async 1–3s) → ORPHAN_CLEANUP re-close → `[METAAPI] Close … failed: Position not found` (OK=True, log noise + 1 RPC rác/cycle).
- **M2-integrity check (LUẬT 8, chạy thật)**: `exit_log` ngày hôm nay (≥07:00+07) = **69 rows = 69 positions, 1:1 không duplicate**, `SUM(pnl) = +69.35`. Ghosts **KHÔNG có row riêng** — vì `write_exit` (main.py L117) chỉ ghi khi broker close thật (ok). → **M2 day$ restore KHÔNG bị nhiễm ✓** · X1 giữ severity = minor (noise + RPC), không escalate.
- Chênh `day$` in-memory (58.87 @08:51) vs M2-SUM (69.35): do nghĩa counter khác nhau (in-memory strategy-booked vs DB full-SUM). M2 là source-of-truth khi restart → không ảnh hưởng DAILY cap.

### 2.3 Lệnh user "dán 200 dòng cuối"
- open = 0 → không có lệnh nào để đối chiếu RANGE_OFFSET. Lũy tập giá trị nhất = bảng §2.1.
- `.out` **KHÔNG** là nơi xem: từ 08:40 `.out` không có dòng mới (SDK-only); log thật = `scalp5.log` → `grep -vE "engineio\.client|socketio\.client" logs/scalp5.log | tail -200`.

---

## 3. Kiểm Định CROSS_OFFSET / PINGPONG

### 3.1 Toán ví dụ HUMAN (verified)
- Ghép 1: W1 +2.60 + B1 −2.40 = +0.20 ✓ · Ghép 2: W1 +2.60 + R2 −0.80 = +1.80 ✓ · PINGPONG worst: −2.40 −0.50 = −3.01 vs free-fall −5.75 ✓.

### 3.2 Empirical (data live 15/10, sau P2-H)
- **3/3 rổ hôm nay = PRUNE_RECOVERY (1.3–3.0′), 0 BASKET_TIME, 0 PSL_BASKET.**
- Giá trị CROSS_OFFSET hôm nay = "tránh được việc rổ chờ 15–30′" — đã được RECOVERY giải quyết nhanh hơn. open peak = 8 (HB 08:46:50 L=6 H=2) nhưng rổ chỉ sống ≤3′ → **không có slot-starvation hôm nay**.
- Scenario CROSS_OFFSET đích thật: **root adverse kéo dài (không hồi +1.0) + winner ≥+0.9pts chạy song song** → rổ pin slot đến BASKET_TIME (15′/30′) hoặc PSL_BASKET. Chưa xảy ra ngày 15/10 (chưa có dữ liệu ngày-adverse).

### 3.3 Verdict theo component
| Component | Đánh giá first-principles | Verdict |
|---|---|---|
| **PRE-LOCK RESCUE** (winner ≥+0.9pts & pullback ≥0.25 từ peak, cứu loser −0.5..−1.15, net ≥ +$0.30) | P2-H KHÔNG có: loser tới −1.2 → đẻ hedge → rổ MỚI (chiếm 2 slot + rủi BASKET_TIME). Rescue chặn sớm = **prevention** (giống M3 ngăn burst — cùng triết lý). Risk cơ hội: bắt runner sớm +0.9 (≈+$1.32) thay TP +1.5 (+$2.52) = −$1.20/đơn nếu range ĐẬP (breakout) — M0-IMPULSE guard chỉ chặn partial; ngày breakout ròng C7 thua so với để chạy TP. Guard bổ sung: chỉ rescue khi M0 = RANGE/CREEP (không V-REV). | **CHẤP (C7-spike)** — 20 dòng, gate bằng replay 12d (C7-ON vs OFF, KPI: số rescue, PnL delta 30′ của lệnh bị rescue) |
| **BASKET-OFFSET** (winner ≥ +$0.30 net giải phóng rổ LOCKED) | Overlap RECOVERY (root thuận ≥+1.0 → đã đóng cặp); phần "không overlap" = root adverse + winner to — ngày adverse. Giá trị = giảm slot-min, không đổi PnL (net vẫn ≥ +0.30 dương). Low priority — RECOVERY + PSL_BASKET −6.48 + BASKET_TIME đã giới hạn damage. | **DEFER (C8)** — chỉ xét nếu KPI slot-min ngày adverse xấu |
| **PINGPONG** (tỉa chân thắng ở biên + stop ±0.25pts chân còn lại + tỉa nốt khi pnl+C ≥ 0) | (i) Stop 0.25pts < gate M3 0.35pts **và** < burst-span thực tế 0.43pts (07:05 incident) → trong range, wick 0.25–0.5pts là noise → **false-trip thường trực** (đóng chân âm sớm hơn điểm tối ưu, mất thêm −0.50 đúng định nghĩa). (ii) Redundant: PSL_BASKET −6.48 (top-of-function breaker C3) đã chặn tail −5.75 mà PINGPONG muốn tránh; HEDGE_TAKE_PAIR + BASKET_TIME cover trọn vòng đời rổ. (iii) Re-introduce **state post-take** (chờ tỉa nhịp 2 + stop) — chính là dạng tail-complexity HUMAN đã duyệt XÓA (nhánh UNWOUND). (iv) "Không bắt chân âm hồi về giá mở" = P2-H đã làm (PRUNE_RECOVERY chỉ cần root +1.0, không cần full-recovery). | **TỪ CHỐI** |

### 3.4 C7 spike — spec (nếu HUMAN duyệt)
- Vị trí: solo-loop trong `scalp_strategy.py` (cùng tầng với ORPHAN_CLEANUP), O(N), N ≤ 8.
- Dữ liệu có sẵn: `self.peak_fav: Dict[pos_id]` (L62, đỉnh lãi thuận per-position) — thay `pos.peak_pts` trong pseudo-code; "is_naked" = không nằm trong `self.hedge_baskets` registry (root & leg đều có id trong registry).
- Điều kiện trigger (cần TẤT CẢ): `M0 ∈ {RANGE, CREEP}` · `open ≥ 2` · winner W: naked, `pnl_W ≥ +0.9pts` và `peak_fav[W] − pnl_W ≥ 0.25pts` (chững lại) · loser R: naked, `−1.15 ≤ pnl_R ≤ −0.5pts` (trước ngưỡng hedge −1.2), `age_R < 15′` · `pnl_W$ + pnl_R$ ≥ +0.30` · mỗi tick rescue tối đa 1 cặp (winner lớn nhất + loser nặng nhất gánh được).
- Reason log: `CROSS_RESCUE_WIN` / `CROSS_RESCUE_LOSER`.
- Gates: `py_compile` · `test_offline` pin ON 565 / OFF 493 **KHÔNG đổi** (12-10 data không có M0-tag → C7 no-op offline = chấp nhận, accept gate = LIVE-KPI) · replay `_replay_hedge.py` C7-ON (M0 proxy từ kinematics 12d nếu có) — nếu replay không support M0 per-tick thì C7 chỉ có live-gate (accept criterion: ≥3 rescue/24h & net PnL rescue-pair > 0 sau 30′ theo dõi).
- Config mới: `CROSS_RESCUE_ENABLE=True`, `CROSS_RESCUE_WIN_PTS=0.9`, `CROSS_RESCUE_PULLBACK_PTS=0.25`, `CROSS_RESCUE_LOSS_MIN_PTS=-1.15`, `CROSS_RESCUE_MIN_NET_USD=0.30` (append-only ✓).

---

## 4. Lựa Chọn Thực Thi (1 merge + 1 restart cho combo, theo bài học P2-H)
| Option | Nội dung | Dòng | Restart |
|---|---|---|---|
| (a) C5 | X1 exit-grace 20s (sync RECOVER) + X2 branch `leg_type=="HEDGE"` | ~7 | ✓ |
| (b) C7-spike | PRE-LOCK RESCUE + config + replay-gate | ~45 (code+config+test) | ✓ |
| (c) LOGSPLIT | DailyUTCFileHandler + boot self-cleanup + boot .out daily | ~35 | ✓ (tự rotate sau deploy) |
| (d) F5 | init-SystemExit → backoff như StreamStalled | ~5 | ✓ |
| (e) monitor-only | KPI P2-H §5 (hedge-cost · 0 PRUNE-INSTANT · worst rổ ≤ −6.48±tick · slot-min · RECOVERY-churn) | — | — |

Gợi ý: **combo (a)+(c)+(d) = "C5+LOGSPLIT+F5"** (giới ~47 dòng, 1 restart) + (b) C7 chạy riêng có replay-gate (không gấp, KPI-adverse-day là điều kiện kích hoạt).
