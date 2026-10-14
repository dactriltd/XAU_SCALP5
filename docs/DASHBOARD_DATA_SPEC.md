# XAU_SCALP5 — SPEC: CHUẨN HOÁ DỮ LIỆU CHO DASHBOARD (rev 1 · 14/10 · CHƯA CODE)

> Mục tiêu (lệnh user 14/10): chuẩn hoá dữ liệu phục vụ bot — lưu trữ phù hợp, ghi đủ & đúng
> để (a) vẽ mọi biểu đồ trên dashboard, (b) hiển thị thông báo hoạt động của bot lên dashboard HTML.
> Tài liệu này = CHUẨN (contract). Việc code/migration là bước kế tiếp, phê duyệt theo §7.

## 0. NGUYÊN TẮC CHUẨN HOÁ (5 LUẬT)

1. **NGUỒN DUY NHẤT (SOT) = SQLite `data/scalp5.db`.** Mọi chart/thông báo = RENDER thuần từ DB.
   JSON (scup5.status.json · verify_report · state_snapshot) = DERIVED / state-cache, KHÔNG phải nguồn KPI.
2. **Mọi ghi DB qua 1 kết nối storage duy nhất (WAL, batch-commit).** Bỏ `tlog()` ad-hoc
   (main.py: mở 1 connection MỖI row — race + chậm + ngoài transaction strategy).
3. **THỜI GIAN: DB = epoch giây UTC (INTEGER).** Hiển thị +07 (VN) do dashboard convert (hằng `TZ_OFFSET=+7`).
   Không lưu timezone, không lưu string datetime. ROL = 21:45Z (04:45+07).
4. **ĐƠN VỊ CHUẨN:** giá = REAL USD (XAUUSDm) · PnL = REAL $ tại lot chuẩn 0.02 (1 pt = $2) ·
   khoảng cách = pts · tick-phút = 60 tick (spec §3 rev 6). Lot đổi → lưu `lot` trên từng row, PnL$ tính lại được.
5. **IDEMPOTENT: mọi bảng sự kiện có PK/UNIQUE → ghi lặp = upsert, không duplicate.**
   `exit_log` UNIQUE(pos_id) (spec #16) · lỗi close (FAIL) KHÔNG ghi exit_log — ghi `evt(CLOSE_FAIL)` thay vào.

Retention chuẩn (bảo toàn cho replay/KPI):

| Bảng | Giữ | Lý do |
|---|---|---|
| entry_log / exit_log / evt / kpi_session / lvl | **VÔ HẠN** (~200 row/ngày, <5MB/năm) | KPI, audit, replay E6 |
| candles m1 | 14d (có) · m5/m15 90d · 1h/4h/1d VÔ HẠN (structural, chưa purge) | replay m1 · reference frame |
| ticks | 7d (có, sparse) | tick-level chỉ 7d — note KPI |
| heartbeat | 14d | liveness |
| regime_log | 30d | phân bố regime, chẩn đoán |
| account_snapshots | gộp vào heartbeat (deprecate bảng riêng) | cân bằng 5′ đủ |

## 1. THỰC TRẠNG (evidence 14/10, đọc DB + grep code)

| Dữ liệu | Trạng thái | Vấn đề chuẩn hoá |
|---|---|---|
| `candles` | ✅ đang ghi, UNIQUE ✓ | 1h stale 10/12 · 4h 10/03 · 1d 10/05 → BACKFILL (spec §14 #22) |
| `entry_log` | ⚠️ ad-hoc (main.py:56, tlog:319) | không UNIQUE · không index · thiếu `side/lot/regime/src/strategy_ver` |
| `exit_log` | ⚠️ ad-hoc (main.py:60, tlog:327) | **61 row duplicate** (134→73 dedup) · thiếu mfe/mae/duration |
| `ticks` | ⚠️ sparse: 14 603 row / 18.5h (≈22 row/′) | không đủ cho replay tick — replay chuẩn = m1 (đã thống nhất) |
| `trades` | ❌ 0 row — `save_trade` KHÔNG được gọi ở main/src | = broker-truth audit (giữ, do reconcile job ghi) |
| `daily_stats` | ❌ 0 row | **DEPRECATE → `kpi_session`** (session 04:45, không 00:00) |
| `kinematics` | ❌ 0 row | giữ schema, KHÔNG ghi (V2 dùng drift5m + levels; ATR tính từ candles) |
| `account_snapshots` | ❌ 0 row | gộp trường balance/equity/margin vào `heartbeat` (5′) |
| `swing_fractal/points` | ❌ 0 row | giữ schema; LVL chuẩn mới = bảng `lvl` (spec rev 7 §14) |
| `gap_markers` | ❌ 0 row (schema có) | 63 phút KNOWN-EMPTY (audit 13/10) đang chỉ nằm trong log/báo cáo → **chuẩn hoá: ghi vào bảng này + evt(GAP_KNOWN)** |
| JSON ×3 (status/verify_report/state_snapshot) | đang dùng | = state-cache/derived — giữ nhưng không phải nguồn KPI |
| Dashboard HTML | ❌ không có (0 file .html) | BUILD MỚI (contract §3) |
| Thông báo | ⚠️ Telegram ad-hoc (entry/exit/daily-cap), không persistence | → bảng `evt` (§4) |

## 2. SCHEMA MỤC TIÊU (chuẩn DDL)

### 2.1 Nâng cấp entry_log / exit_log (ALTER — giữ data cũ)
```sql
-- step 0 (migration M1): dedup exit_log — giữ row ts NHỎ NHẤT mỗi pos_id (spec #16, đã duyệt)
ALTER TABLE entry_log ADD COLUMN side TEXT NOT NULL DEFAULT '';
ALTER TABLE entry_log ADD COLUMN lot REAL NOT NULL DEFAULT 0.02;
ALTER TABLE entry_log ADD COLUMN regime TEXT NOT NULL DEFAULT '';
ALTER TABLE entry_log ADD COLUMN src TEXT NOT NULL DEFAULT '';      -- EDGE | FZ-FADE | R1 | R2 (rev 7)
ALTER TABLE entry_log ADD COLUMN strategy_ver TEXT NOT NULL DEFAULT 'v0';
CREATE UNIQUE INDEX IF NOT EXISTS uq_entry_pos ON entry_log(pos_id);
CREATE INDEX IF NOT EXISTS idx_entry_ts ON entry_log(ts DESC);

ALTER TABLE exit_log ADD COLUMN mfe_pts REAL NOT NULL DEFAULT 0;
ALTER TABLE exit_log ADD COLUMN mae_pts REAL NOT NULL DEFAULT 0;
ALTER TABLE exit_log ADD COLUMN duration_s INTEGER;
ALTER TABLE exit_log ADD COLUMN strategy_ver TEXT NOT NULL DEFAULT 'v0';
CREATE UNIQUE INDEX IF NOT EXISTS uq_exit_pos ON exit_log(pos_id);
CREATE INDEX IF NOT EXISTS idx_exit_ts ON exit_log(ts DESC);
```
> `side`/`regime`/`src` cho row cũ (10/13–14) = rỗng — dashboard render mặc định "v0/—".

### 2.2 Bảng MỚI (chuẩn DDL)
```sql
-- LVL ladder (spec rev 7 §14: zone m1 ±2 rolling, touches, strong, DEAD close ∓2.5)
CREATE TABLE lvl (
  zone_key TEXT NOT NULL,          -- 'H:4166.30' (kind:px .2f)
  symbol TEXT NOT NULL, tf TEXT NOT NULL DEFAULT 'm1',
  px REAL NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('H','L')),
  t_pivot INTEGER NOT NULL, t_conf INTEGER NOT NULL,
  touches INTEGER NOT NULL DEFAULT 0, t_last_touch INTEGER,
  strong INTEGER NOT NULL DEFAULT 0,
  alive INTEGER NOT NULL DEFAULT 1, dead_ts INTEGER,
  updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  PRIMARY KEY (symbol, tf, zone_key)
);
CREATE INDEX IF NOT EXISTS idx_lvl_alive ON lvl(symbol, tf, alive, px DESC);

-- M0 REGIME (spec rev 6 #11: snapshot + tag, hysteresis 2 tick-phút)
CREATE TABLE regime_log (
  ts INTEGER NOT NULL,
  regime TEXT NOT NULL,            -- IMPULSE | V-REV | RANGE | CREEP
  regime_side TEXT NOT NULL DEFAULT '',   -- up | down | ''
  speed REAL, form_ratio REAL, extreme_age REAL,
  snap TEXT,                       -- JSON đầy đủ (debug)
  PRIMARY KEY (ts)
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_log(ts DESC);

-- SỰ KIỆN / THÔNG BÁO (feed dashboard, §4)
CREATE TABLE evt (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  category TEXT NOT NULL,          -- TRADE | RISK | REGIME | DATA | SYSTEM
  level TEXT NOT NULL CHECK(level IN ('OK','INFO','WARN','CRIT')),
  code TEXT NOT NULL,             -- enum §4.2
  msg TEXT, ref_pos TEXT, payload TEXT   -- payload = JSON
);
CREATE INDEX IF NOT EXISTS idx_evt_ts ON evt(ts DESC, id DESC);

-- KPI theo PHIÊN (04:45+07 → 04:45+07) — thay daily_stats
CREATE TABLE kpi_session (
  session_start INTEGER NOT NULL PRIMARY KEY,  -- epoch ROL
  session_end INTEGER,
  day_pnl REAL NOT NULL DEFAULT 0,             -- SUM(pnl) exit_log DEDUP (chuẩn #16)
  wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
  entries INTEGER NOT NULL DEFAULT 0, exits INTEGER NOT NULL DEFAULT 0,
  psl_hits INTEGER NOT NULL DEFAULT 0, reverse_hits INTEGER NOT NULL DEFAULT 0,
  blocks INTEGER NOT NULL DEFAULT 0,           -- lệnh bị gates chặn (SKIP)
  regime_dist TEXT, avg_spread REAL, avg_tick_min REAL, max_dd REAL,
  notes TEXT,
  created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- HEARTBEAT (5′, thay logs/scalp5.status.json làm nguồn) + account snapshot
CREATE TABLE heartbeat (
  ts INTEGER NOT NULL PRIMARY KEY,
  px REAL, drift5m REAL, mode TEXT, regime TEXT,
  open_count INTEGER, day_pnl REAL, halted INTEGER, k_eff INTEGER,
  balance REAL, equity REAL, free_margin REAL,
  tick_rate REAL, lvl_alive INTEGER
);
```

## 3. DASHBOARD DATA CONTRACT (biểu đồ ← bảng, JSON feed)

### 3.1 Map biểu đồ → nguồn
| Biểu đồ / khối (dashboard HTML) | Nguồn (SELECT) | Window |
|---|---|---|
| **Giá–Thời** (L1, cùng chuẩn _chart_px_time.py): nến + marker ● vào / ■ ra + box KPI | `candles(tf)` + `entry_log` + `exit_log`(dedup) | 60′–1d, bucket do user chọn |
| **Vạch LVL** (L2/L6): ═ H-alive / ─ L-alive + tag touches/strong | `lvl` (alive) | phiên |
| **Reference m15/1h/4h** (chấm + tag) | `candles(m15/1h/4h)` + fractals rebuild | phiên (⚠️ chờ backfill §14 #22) |
| **Regime timeline** (dải màu) | `regime_log` | phiên |
| **Equity/PnL curve** | `kpi_session.day_pnl` (luỹ kế) + `exit_log` (intra-session) | 7–30d |
| **KPI box** (day$, WR, PSL, FUSE, K_eff, halted) | `kpi_session` (phiên hiện tại) + `heartbeat` (live) | live |
| **Vị thế mở + unrealized** | `positions` (state live) + `heartbeat.balance/equity` | live |
| **Feed thông báo** | `evt` (ts DESC, filter category/level) | 100 items |
| **Data-quality** (gap, stale TF, bot-chết?) | `gap_markers` + `candles(MAX ts per tf)` + `heartbeat(MAX ts)` | live |

### 3.2 JSON contract (dashboard fetch; hosting xem §7-D1)
- `GET /api/state` (poll 5s): `{ts, px, drift5m, mode, regime, day_pnl, halted, k_eff, open:[{pos,side,entry,px,upl,tp}], levels:{H:[[px,touches,strong]],L:[...]}}`
- `GET /api/series?from&to&tf` (on-demand): `{candles:[[ts,o,h,l,c,v]], entries:[{ts,pos,side,px,tp,src,regime}], exits:[{ts,pos,reason,px,pnl}], levels:[...], regime:[{ts,regime}]}`
- `GET /api/kpi?from&to`: `{sessions:[{start,day_pnl,wins,losses,entries,psl_hits,wr}], cumulative}`
- `GET /api/events?limit&cat&level`: `[{ts,category,level,code,msg,ref_pos,payload}]`
- Mọi ts trong JSON = epoch UTC (dashboard render +07). `pnl` = $. `wr` = wins/(wins+losses).

## 4. CHUẨN THÔNG BÁO (evt catalog)

### 4.1 Luật ghi evt
- Ghi MỖI sự kiện §4.2 đúng lúc nó xảy ra (cùng transaction với entry/exit log).
- `ref_pos` = pos_id nếu có; `payload` = JSON tối thiểu cho render (px, pnl$, reason, n…).
- `msg` = 1 dòng người đọc được (VN), không phụ thuộc tz (giờ hiển thị UI convert +07).

### 4.2 Code (category · code · level · trigger)
| category | code | level | Trigger | payload |
|---|---|---|---|---|
| TRADE | ENTER | INFO | entry OK (entry_log row) | side,px,tp,src,regime,gates_skipped[] |
| TRADE | ENTER_SKIP | INFO | bị gates chặn (G2/G-DIR/M0/K_eff) | rule, px, mức liên quan |
| TRADE | EXIT | INFO | bot-initiated exit (TP/PSL/REVERSE/ROL/TIME/S_BREAK…) | reason, px, pnl$, dur |
| TRADE | EXIT_SYNC | INFO | broker-side fill (TP_BROKER, SYNC_BROKER, ADOPT) | pos, px, pnl$ |
| RISK | PSL | WARN | lệnh chạm PSL −6$ | pos, pnl$ |
| RISK | REVERSE | WARN | REVERSE −3$ (≤1/pos) | pos |
| RISK | ALARM_D30 | WARN | day$-dedup ≤ −30$ | day$ |
| RISK | ALARM_D50 | CRIT | ≤ −50$ | day$ |
| RISK | ALARM_D75 | CRIT | ≤ −75$ (FUSE: K_eff ↓1/2) | day$, k_eff_mới |
| RISK | DAILY_CAP | CRIT | at_daily_cap (halt entry phiên) | day$ |
| REGIME | REGIME_SHIFT | INFO | M0 đổi regime (hysteresis xác nhận) | old→new, speed, extreme_age |
| DATA | GAP_FOUND | WARN | m1 thiếu ≥ N phút trong phiên | tf, t0, t1, n_missing |
| DATA | GAP_KNOWN | INFO | gap = KNOWN-EMPTY-GAP (gap_markers hit) | tf, t0, t1 |
| DATA | CANDLES_STALE | WARN | MAX(ts) candles(tf) trễ > 2× chu kỳ tf | tf, last_ts |
| DATA | EXIT_DUP_PURGED | INFO | migration/dedup exit_log (row bị bỏ) | n_purged |
| SYSTEM | BOOT | INFO | khởi động OK (PID-FILE, probe balance) | pid, balance |
| SYSTEM | SHUTDOWN | INFO | dừng sạch | state_saved |
| SYSTEM | STATE_SNAP | INFO | save/load state_snapshot | file, age |
| SYSTEM | CLOSE_FAIL | CRIT | 'Position not found' loop / exit fail ×N | pos, n_retry |
| SYSTEM | ADOPT | WARN | adopt vị thế orphan từ broker | n_pos |
| SYSTEM | TOKEN_WARN | CRIT | JWT exp ≤ 7 ngày | exp_date |
| (HEART) | — | — | heartbeat 5′ → bảng `heartbeat` (KHÔNG ghi evt — tránh spam) | — |

> Telegram (có) = MIRROR chọn lọc của evt (mức WARN/CRIT + ENTER/EXIT) — 1 nguồn, 2 kênh.

## 5. KỶ LUẬT GHI (đủ & đúng)

1. **Batch writer**: 1 connection storage (WAL) cho toàn bộ bot; commit theo batch (≤1s hoặc 32 row).
   ENTRY/EXIT/evt cùng 1 transaction (entry + evt(ENTER) nguyên tử).
2. **FAIL row**: close/exit lỗi broker (CLOSE_FAIL) → KHÔNG ghi exit_log (spec #16) → ghi evt(CLOSE_FAIL)
   + retry re-adopt (spec #15). Row exit_log chỉ khi PnL đã có (bot-initiated) hoặc broker-truth (SYNC_BROKER).
3. **day$ chuẩn = SUM(pnl) exit_log dedup theo pos_id** (spec #14) — `executor.day_loss` (in-memory)
   chỉ là MIRROR so khớp (chênh > 0.01$ → evt(DATA, WARN)).
4. **KPI session chốt**: tại ROL 04:45+07 → upsert `kpi_session` (phiên trước) + đóng heartbeat day_pnl;
   giữa phiên: `kpi_session` cập nhật incremental (upsert, idempotent).
5. **LVL (rev 7)**: ghi `lvl` khi zone confirm (t_conf) + update touches/strong/alive/dead_ts khi thay đổi;
   BOOT = rebuild-from-candles (spec §14.2 — swing_fractal rỗng không dùng, zone tính lại từ m1 ±2).
6. **Regime (M0)**: ghi `regime_log` khi snapshot đổi (hysteresis 2 tick-phút, #11) + tag vào `entry_log.regime`.
7. **Gap**: phát hiện m1-trong-ngày thiếu → evt(GAP_FOUND); broker xác nhận "0 candles" → upsert `gap_markers` (hiện 0 row — chưa có writer)
   + evt(GAP_KNOWN). Dashboard "Data-quality" block đọc 2 bảng này.
8. **Tần suất ghi (budget)**: m1 close 1 row + kinematics OFF + ticks theo stream (có) + heartbeat 5′
   + regime theo shift + evt theo sự kiện → <200 row/giờ (trừ ticks) — an toàn SQLite WAL.

## 6. MIGRATION (M1–M4, offline, bot stopped hoặc WAL-safe)

| Bước | Việc | Bằng chứng hoàn tất |
|---|---|---|
| M1 | Dedup exit_log (giữ ts sớm nhất/pos, ~61 row) → ALTER entry/exit_log + UNIQUE + index | `SELECT COUNT(*) - COUNT(DISTINCT pos_id) FROM exit_log` = 0 |
| M2 | CREATE lvl, regime_log, evt, kpi_session, heartbeat + index | `.schema` đủ bảng |
| M3 | Backfill: lvl (rebuild 18.5h m1) + kpi_session (từ exit_log) + evt(BOOT/EXPORT) seed | SELECT COUNT(*) các bảng > 0 |
| M4 | Backfill 1h/4h/1d (gap_filler multi-TF — spec §14 #22) | MAX(ts) 1h/4h/1d = hiện tại |

## 7. NGHIỆM THU "ĐỦ & ĐÚNG" (test trước khi dashboard ship)

- **T1 (đủ)**: phiên chạy ≥ 12h → DB có: entry_log n = log-vào · exit_log UNIQUE ✓ · lvl (zone alive+dead) ·
  regime_log (≥ các lần shift) · evt (mọi code phát sinh) · kpi_session (1–2 row) · heartbeat (≥ 72 row/6h).
- **T2 (đúng, chart)**: render chart giá–thời từ DB = diff với `_chart_px_time.py` (chuẩn text-box) = 0 sai lệch marker/px.
- **T3 (đúng, KPI)**: `kpi_session.day_pnl` = `SUM(pnl) exit_log dedup` (chênh ≤ 0.01$); WR = wins/total khớp chart.
- **T4 (live)**: dashboard HTML đọc /api/* — liveness: heartbeat trễ > 15′ → dashboard tự báo "BOT DEAD?";
  feed evt cập nhật ≤ 15s; chart + KPI không bao giờ tính PnL (chỉ render).

## 8. QUYẾT ĐỊNH CÒN MỞ (cần CHAIRMAN chốt trước code)

- **D1 — Hosting dashboard**: ✅ **CHỐT 14/10 = phương án (a) HTTP read-only nhúng trong tiến trình bot** (stdlib, bind 127.0.0.1:7852, DB read-only, HTML ở repo). Đúng lệnh #23 (1 tiến trình).
  (Phương án (b) tiến trình riêng và (c) HTML poll JSON file — đã loại.)
- **D2 — Cảnh báo CRIT highlight đỏ trên feed**: ALARM_D50/75 · CLOSE_FAIL · TOKEN_WARN · GAP_FOUND > 60′ · DAILY_CAP.
- **D3 — Retention evt/kpi_session = vô hạn** (~200 row/ngày; DB hiện 20MB → +~2MB/tháng, <1% tăng) — confirm.
- **D4 — ticks**: giữ 7d (sparse, không dùng cho replay) hay tăng 14d? (chỉ ảnh hưởng dung lượng)
