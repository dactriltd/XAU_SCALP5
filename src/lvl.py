"""src/lvl.py — LVL LADDER M1 (spec rev 7 §14 · port _replay_lvl.py đã gate E6).

Mô hình zone m1 (cùng công thức replay E6):
  pivot: nến i có high > high 4 nến kề (i±1, i±2) → H tại high · low < low 4 nến kề → L
  t_conf = ts nến i+2 + 60s (2 nến xác nhận)
  gộp zone cùng kind: Δpx ≤ ZONE_PTS (0.5pts) VÀ Δcandle ≤ ZONE_SPAN (30') → px = max(H)/min(L)
  STRONG = touches ≥ LVL_TOUCH (chạm = high/low trong ±LVL_BAND, 2 chạm cách ≥ LVL_SEP_MIN')
  DEAD   = H-ONLY: m1 CLOSE ≤ P−LVL_DEAD (2.5pts) (parity E6 đã gate: _replay_lvl.py L105 chỉ H)
          L-zone KHÔNG dead → chỉ age-cap LVL_AGE_MIN (240') · L-death (∓2ch) = rev-sau, cần re-gate
          wick-exempt: wick KHÔNG giết, chỉ close

DB: bảng `lvl` (DDL docs/DASHBOARD_DATA_SPEC.md §2.2, PK (symbol, tf, zone_key)) ·
   UPSERT khi m1 close. conn read-only → persist bị skip (engine chạy in-memory).
Hằng đọc qua getattr(cfg, "X", default) — default khớp giá trị rev-7, không hardcode trần trụi.

2 entry-point cùng lõi (LvlEngine._on_candle):
  rebuild_from_candles(conn, symbol) — BOOT: tái tính từ LVL_REBUILD_M1 nến m1 cuối trong DB
  on_m1_close(conn, ts, bar)        — LIVE: main.py sẽ gọi sau mỗi m1 close (CHƯA wire)
Query API (gọi sau rebuild/on_m1_close): strong_zones(side, now) · g2_blocked(side, px, now) · extreme15(now)
"""
import sqlite3
from collections import deque
from typing import Dict, List, Optional, Tuple

try:
    from src import config as cfg
except ImportError:  # src/ làm cwd (thói quen module cũ)
    import config as cfg  # type: ignore


def _C(name: str, default):
    """Đọc hằng từ config (bổ sung S3-A), fallback default rev-7."""
    return getattr(cfg, name, default)


# --- hằng rev-7 (config.py thêm sau — default luôn khớp rev-7) ---
LVL_TOUCH: int = _C("LVL_TOUCH", 2)              # touches ≥ N = STRONG
LVL_BAND: float = _C("LVL_BAND", 0.5)            # bán kính chạm zone (pts)
ZONE_PTS: float = _C("ZONE_PTS", 0.5)            # gộp zone cùng kind: Δpx (pts)
ZONE_SPAN: int = _C("ZONE_SPAN", 30)             # gộp zone: Δ thời gian (candle m1 ≈ phút)
LVL_DEAD: float = _C("LVL_DEAD", 2.5)            # DEAD (H-only, E6 parity): m1 close ≤ P− (pts) · L-zone age-cap
G2LVL_PTS: float = _C("G2LVL_PTS", 2.0)          # G2: px cách zone strong·alive ≤ (pts) → CHẶN
LVL_SEP_MIN: int = _C("LVL_SEP_MIN", 6)          # 2 chạm cách ≥ (E6; chưa có trong config rev-7)
LVL_AGE_MIN: int = _C("LVL_AGE_MIN", 240)        # zone hết hạn sau (E6, như FZ_RECENT)
LVL_REBUILD_M1: int = _C("LVL_REBUILD_M1", 600)  # cửa sổ rebuild boot = 10h (trùng S1_SWINGS)

# DDL đúng DASHBOARD_DATA_SPEC §2.2 (cột + PK); index IF NOT EXISTS
DDL_TABLE = """
CREATE TABLE IF NOT EXISTS lvl (
  zone_key TEXT NOT NULL,          -- 'H:4166.30' (kind:px .2f)
  symbol TEXT NOT NULL, tf TEXT NOT NULL DEFAULT 'm1',
  px REAL NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('H','L')),
  t_pivot INTEGER NOT NULL, t_conf INTEGER NOT NULL,
  touches INTEGER NOT NULL DEFAULT 0, t_last_touch INTEGER,
  strong INTEGER NOT NULL DEFAULT 0,
  alive INTEGER NOT NULL DEFAULT 1, dead_ts INTEGER,
  updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
  PRIMARY KEY (symbol, tf, zone_key)
)"""
DDL_INDEX = "CREATE INDEX IF NOT EXISTS idx_lvl_alive ON lvl(symbol, tf, alive, px DESC)"
UPSERT_SQL = """
INSERT INTO lvl (zone_key, symbol, tf, px, kind, t_pivot, t_conf, touches,
                 t_last_touch, strong, alive, dead_ts, updated_at)
VALUES (?, ?, 'm1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol, tf, zone_key) DO UPDATE SET
  px=excluded.px, t_pivot=excluded.t_pivot, t_conf=excluded.t_conf,
  touches=excluded.touches, t_last_touch=excluded.t_last_touch,
  strong=excluded.strong, alive=excluded.alive, dead_ts=excluded.dead_ts,
  updated_at=excluded.updated_at"""


class LvlEngine:
    """Lõi zone m1 — rebuild (nhiều nến) và live (1 nến/đóng) cùng chạy _on_candle."""

    def __init__(self, symbol: str = "XAUUSDm"):
        self.symbol = symbol
        self.zones: Dict[str, dict] = {}  # zone_key → zone
        self.bars: deque = deque()         # (ts, o, h, l, c) nến m1 đã đóng, tối đa LVL_REBUILD_M1
        self._dirty: set = set()           # zone cần UPSERT
        self._readonly = False             # conn read-only → bỏ qua persist

    # ---------- lõi (cùng 1 hàm cho rebuild + live) ----------
    def _on_candle(self, ts: int, o: float, h: float, l: float, c: float) -> None:
        self.bars.append((ts, o, h, l, c))
        if len(self.bars) > LVL_REBUILD_M1:
            self.bars.popleft()
        for z in self.zones.values():
            # DEAD (H-ONLY — parity E6 đã gate: _replay_lvl.py L105 chỉ H · L-zone chỉ age-cap
            #   LVL_AGE_MIN=240' · L-death ∓2ch = rev-sau cần re-gate — decision owner 14/10, STATE.md).
            #   wick-exempt: chỉ CLOSE giết, high/low không.
            if z["dead_ts"] is None and z["kind"] == "H" and c <= z["px"] - LVL_DEAD:
                z["dead_ts"] = ts
                z["alive"] = 0
            # TOUCH: nến từ t_conf trở đi, trong band ±LVL_BAND, cách ≥ LVL_SEP_MIN'
            if ts >= z["t_conf"]:
                hit = (h >= z["px"] - LVL_BAND) if z["kind"] == "H" else (l <= z["px"] + LVL_BAND)
                if hit and (z["t_last_touch"] is None or ts - z["t_last_touch"] >= LVL_SEP_MIN * 60):
                    z["touches"] += 1
                    z["t_last_touch"] = ts
            z["strong"] = 1 if z["touches"] >= LVL_TOUCH else 0
            self._dirty.add(z["zone_key"])
        # PIVOT: nến i = "-3" vừa được xác nhận khi nến i+2 (hiện tại) đóng — cần đủ 5 nến
        if len(self.bars) >= 5:
            i = self.bars[-3]
            if i[2] > max(self.bars[-5][2], self.bars[-4][2], self.bars[-2][2], self.bars[-1][2]):
                self._merge_or_create("H", i[2], i[0], ts + 60)
            if i[3] < min(self.bars[-5][3], self.bars[-4][3], self.bars[-2][3], self.bars[-1][3]):
                self._merge_or_create("L", i[3], i[0], ts + 60)

    def _merge_or_create(self, kind: str, px: float, t_pivot: int, t_conf: int) -> None:
        """Gộp pivot vào zone cùng kind (Δpx ≤ ZONE_PTS, Δcandle ≤ ZONE_SPAN) hoặc tạo mới."""
        for z in self.zones.values():
            if z["kind"] == kind and abs(z["px"] - px) <= ZONE_PTS \
                    and (t_pivot - z["i_last"]) <= ZONE_SPAN * 60:
                z["px"] = max(z["px"], px) if kind == "H" else min(z["px"], px)
                z["i_last"] = t_pivot
                z["t_conf"] = min(z["t_conf"], t_conf)  # giữ mốc confirm sớm nhất
                self._dirty.add(z["zone_key"])
                return
        base = f"{kind}:{px:.2f}"
        key, n = base, 2
        while key in self.zones:  # trùng giá làm tròn, cách > ZONE_SPAN → suffix
            key = f"{base}-{n}"
            n += 1
        self.zones[key] = dict(zone_key=key, kind=kind, px=px, t_pivot=t_pivot, t_conf=t_conf,
                                i_last=t_pivot, touches=0, t_last_touch=None,
                                strong=0, alive=1, dead_ts=None)
        self._dirty.add(key)

    def _persist(self, conn: sqlite3.Connection, now_ts: int, full: bool = False) -> None:
        """UPSERT zone dirty vào bảng lvl. full=True (rebuild): xóa trước → bảng = đúng engine."""
        if not self._dirty:
            return
        try:
            conn.execute(DDL_TABLE)
            conn.execute(DDL_INDEX)
            if full:
                conn.execute("DELETE FROM lvl WHERE symbol=? AND tf='m1'", (self.symbol,))
        except sqlite3.OperationalError:
            self._readonly = True  # conn read-only (hoặc bảng chưa tạo được) → chỉ in-memory
            return
        rows = [(z["zone_key"], self.symbol, z["px"], z["kind"], z["t_pivot"], z["t_conf"],
                  z["touches"], z["t_last_touch"], z["strong"], z["alive"], z["dead_ts"], now_ts)
                for z in self.zones.values() if z["zone_key"] in self._dirty]
        try:
            conn.executemany(UPSERT_SQL, rows)
            conn.commit()
        except sqlite3.OperationalError:
            self._readonly = True
            return
        self._dirty.clear()


_engine: Optional[LvlEngine] = None


def rebuild_from_candles(conn: sqlite3.Connection, symbol: str = "XAUUSDm") -> LvlEngine:
    """BOOT: tái tính zone từ LVL_REBUILD_M1 nến m1 cuối trong DB (chỉ SELECT + DDL IF NOT EXISTS).

    conn có thể read-only (URI file:...?mode=ro): engine vẫn chạy, persist tự skip.
    """
    global _engine
    eng = LvlEngine(symbol)
    rows: List[Tuple] = conn.execute(
        "SELECT timestamp, open, high, low, close FROM candles "
        "WHERE symbol=? AND timeframe='1m' ORDER BY timestamp DESC LIMIT ?",
        (symbol, LVL_REBUILD_M1)).fetchall()
    for ts, o, h, l, c in reversed(rows):
        eng._on_candle(ts, o, h, l, c)
    _engine = eng
    eng._persist(conn, rows[0][0] if rows else 0, full=True)
    return eng


def on_m1_close(conn: sqlite3.Connection, ts: int, bar) -> None:
    """LIVE: main.py gọi khi nến m1 đóng (bar = dict OHLC hoặc tuple (o,h,l,c)).

    conn = sqlite3.Connection đồng bộ; với aiosqlite truyền `conn._conn`.
    Nếu chưa rebuild (engine rỗng): tích lũy nến, zone hình thành sau 5 nến.
    """
    global _engine
    if _engine is None:
        _engine = LvlEngine()
    if isinstance(bar, dict):
        o, h, l, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
    else:
        o, h, l, c = (float(x) for x in bar[:4])
    _engine._on_candle(ts, o, h, l, c)
    _engine._persist(conn, ts)


def _zones_at(side: str, now: int) -> List[dict]:
    """Zone strong·alive·chưa hết hạn của side tại thời điểm now ('S'→H, 'B'→L)."""
    if _engine is None:
        return []
    kind = "H" if side == "S" else "L"
    out: List[dict] = []
    for z in _engine.zones.values():
        if z["kind"] != kind or z["strong"] != 1:
            continue
        if z["dead_ts"] is not None and now >= z["dead_ts"]:
            continue
        if now < z["t_conf"] or now - z["t_conf"] > LVL_AGE_MIN * 60:
            continue
        out.append(dict(px=z["px"], kind=z["kind"], t_conf=z["t_conf"], t_pivot=z["t_pivot"],
                        touches=z["touches"], dead_ts=z["dead_ts"]))
    return out


def strong_zones(side: str, now: int) -> List[dict]:
    """Danh sách zone strong·alive cho side ('S'→zone H, 'B'→zone L) tại thời điểm now."""
    return _zones_at(side, now)


def g2_blocked(side: str, px: float, now: int) -> bool:
    """G2-LVL (rev 7): S CHẶN nếu px nằm trong G2LVL_PTS DƯỚI zone H strong·alive · B mirror."""
    for z in _zones_at(side, now):
        if side == "S" and 0 <= z["px"] - px <= G2LVL_PTS:
            return True
        if side == "B" and 0 <= px - z["px"] <= G2LVL_PTS:
            return True
    return False


def extreme15(now: int) -> Optional[Tuple[float, int, float, int]]:
    """Cực trị 15 nến m1 gần nhất (đã đóng): (high, ts_high, low, ts_low) · None nếu <15 nến.

    now chỉ để đối chiếu — cửa sổ lấy 15 nến đóng gần nhất (không dùng dữ liệu tương lai).
    """
    if _engine is None or len(_engine.bars) < 15:
        return None
    win = list(_engine.bars)[-15:]
    hi = max(win, key=lambda b: b[2])
    lo = min(win, key=lambda b: b[3])
    return (hi[2], hi[0], lo[3], lo[0])
