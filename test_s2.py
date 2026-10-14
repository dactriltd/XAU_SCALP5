"""S2 TEST OFFLINE (bot STOPPED — 0 RPC thật, stub tất cả). Chạy: .venv/bin/python test_s2.py
(a) exit_action: executor.exit trả (pnl, True) → đúng 1 tlog exit_log · (pnl, False) → 0 tlog
(b) in-memory sqlite: schema thật + UNIQUE index · INSERT OR IGNORE cùng pos_id 3 lần → COUNT=1
(c) boot_exit_log_sync + client stub: 1 pos đã có exit row + 1 pos CHƯA có → writer gọi đúng 1 lần
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from src import config as C
from src.scalp_executor import ScalpExecutor


# ─────────────────────────── stubs ───────────────────────────
class RecWriter:
    """Chỉ ghi nhận call (không chạm DB) — cho test (a)."""

    def __init__(self):
        self.calls = []

    async def __call__(self, kind, row):
        self.calls.append((kind, row))


class DbWriter:
    """Mim main.tlog: INSERT OR IGNORE vào db_path (cần schema thật) + ghi nhận call.
    Dùng cho test (c) để chứng minh UNIQUE index → idempotent khi chạy boot 2 lần."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.calls = []

    async def __call__(self, kind, row):
        self.calls.append((kind, row))
        con = sqlite3.connect(self.db_path)
        con.execute(
            f"INSERT OR IGNORE INTO {kind} VALUES ({','.join('?' * len(row))})", row
        )
        con.commit()
        con.close()


class StubTg:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class StubExecutor:
    """Mim executor.exit trả tuple (pnl, ok) theo kịch bản."""

    def __init__(self, pnl, ok):
        self._res = (pnl, ok)
        self.at_daily_cap = False
        self.halted = False
        self.day_loss = 0.0

    async def exit(self, pos_id, px, reason):
        return self._res


class StubClient:
    """get_positions: lần 1 = positions_mua, sau = positions_sau (TP-fill → []).
    close_position trả close_ok (True = close thành công)."""

    def __init__(self, positions_mua, positions_sau, close_ok):
        self._mua = positions_mua
        self._sau = positions_sau
        self.close_ok = close_ok
        self.n_get = 0

    async def get_positions(self):
        self.n_get += 1
        return self._mua if self.n_get == 1 else self._sau

    async def close_position(self, pos_id):
        return self.close_ok


def _pos(pid="P1", profit=5.0):
    return {"id": pid, "type": "POSITION_TYPE_BUY", "side": "buy",
            "openPrice": 4000.0, "magic": C.MAGIC, "profit": profit}


def _deal(pid, et, ts_iso, price=None, profit=0.0, magic=C.MAGIC, symbol=C.SYMBOL):
    """Deal shape camelCase (MetaApi SDK models.py)."""
    return {"id": f"D{pid}{et}", "type": "DEAL_TYPE_BUY", "entryType": et,
            "symbol": symbol, "magic": magic, "time": ts_iso, "brokerTime": ts_iso,
            "price": price, "profit": profit, "positionId": pid}


# ─────────────────────────── (a) exit_action: tlog call count ───────────────────────────
class TestExitAction(unittest.TestCase):
    def test_ok_true_1_tlog(self):
        ex, tg, w = StubExecutor(3.14, True), StubTg(), RecWriter()
        a = {"kind": "EXIT", "pos_id": "P1", "px": 4001.5, "reason": "TP"}
        asyncio.run(main.exit_action(a, 123, ex, tg, writer=w))
        exit_calls = [c for c in w.calls if c[0] == "exit_log"]
        self.assertEqual(len(exit_calls), 1)
        self.assertEqual(exit_calls[0][1], (123, "P1", "TP", 4001.5, 3.14))
        self.assertTrue(any("📤 EXIT" in s for s in tg.sent))

    def test_ok_false_0_tlog(self):
        ex, tg, w = StubExecutor(0.0, False), StubTg(), RecWriter()
        a = {"kind": "EXIT", "pos_id": "P1", "px": 4001.5, "reason": "TIME"}
        asyncio.run(main.exit_action(a, 123, ex, tg, writer=w))
        self.assertEqual(len(w.calls), 0)
        self.assertTrue(any("CLOSE_FAIL" in s for s in tg.sent))


class TestExecutorExitTuple(unittest.TestCase):
    """exit() thật + client stub: tuple (pnl, ok) 3 kịch bản."""

    def _ex(self, client):
        ex = ScalpExecutor(client, C)
        ex.positions.append({"id": "P1", "side": "L", "entry": 4000.0, "entry_ts": 0, "anchor": None})
        return ex

    def test_close_ok(self):
        cl = StubClient([_pos()], [_pos()], True)
        ex = self._ex(cl)
        pnl, ok = asyncio.run(ex.exit("P1", 4001.5, "TP"))
        self.assertTrue(ok)
        self.assertAlmostEqual(pnl, 5.0)          # pnl lấy từ broker profit
        self.assertEqual(ex.positions, [])          # pos đã gỡ

    def test_broker_gone_tp_fill(self):
        # TP fill GIỮA HAI TICK: lúc exit() gọi thì pos đã không còn ở broker (gọi 1 = [])
        # → close trả False nhưng OK (vô hại) · pnl ước lượng theo px-estimate
        cl = StubClient([], [], False)
        ex = self._ex(cl)
        pnl, ok = asyncio.run(ex.exit("P1", 4001.5, "TP"))
        self.assertTrue(ok)
        self.assertAlmostEqual(pnl, 3.0)           # estimate: (4001.5-4000)*2oz
        self.assertEqual(ex.positions, [])

    def test_broker_gone_but_pnl_known_then_close_noop(self):
        # pos cũ có profit, gọi 1 có pos · close fail (đã TP fill) · gọi 2 = [] → OK
        cl = StubClient([_pos()], [], False)
        ex = self._ex(cl)
        pnl, ok = asyncio.run(ex.exit("P1", 4001.5, "TP"))
        self.assertTrue(ok)
        self.assertAlmostEqual(pnl, 5.0)           # lấy profit broker (lúc gọi 1)

    def test_close_fail_pos_still_on_broker(self):
        cl = StubClient([_pos()], [_pos()], False)
        ex = self._ex(cl)
        pnl, ok = asyncio.run(ex.exit("P1", 4001.5, "TIME"))
        self.assertFalse(ok)
        self.assertEqual(len(ex.positions), 1)      # giữ vị thế → tick sau retry, không spam row


# ─────────────────────────── (b) UNIQUE + INSERT OR IGNORE ───────────────────────────
class TestUniqueUpsert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(":memory:")
        cls.con.executescript(main.TELEMETRY_SQL)
        cls.con.execute("CREATE UNIQUE INDEX uq_exit_pos ON exit_log(pos_id)")
        cls.con.execute("CREATE UNIQUE INDEX uq_entry_pos ON entry_log(pos_id)")

    def test_exit_3_inserts_same_pos_count1_earliest_kept(self):
        for ts in (100, 200, 300):  # cùng pos_id, ts tăng dần
            self.con.execute("INSERT OR IGNORE INTO exit_log VALUES (?,?,?,?,?)",
                             (ts, "P1", "TP", 4000.0, 1.0))
        rows = self.con.execute(
            "SELECT ts FROM exit_log WHERE pos_id='P1' ORDER BY ts").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 100)          # row ts sớm nhất được giữ (row gốc từ migration)

    def test_or_ignore_first_write_wins(self):
        # OR IGNORE semantics: row ghi TRƯỚC thắng (migration đã chuẩn hoá ts nhỏ nhất
        # cho data cũ; row mới sinh ra ở thời điểm exit/sync nên write-đầu = ts-sớm)
        for ts in (300, 100):
            self.con.execute("INSERT OR IGNORE INTO exit_log VALUES (?,?,?,?,?)",
                             (ts, "P2", "TP", 4000.0, 1.0))
        rows = self.con.execute("SELECT ts FROM exit_log WHERE pos_id='P2'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 300)


# ─────────────────────────── (c) boot_exit_log_sync ───────────────────────────
class TestBootExitLogSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls.fd)
        con = sqlite3.connect(cls.db_path)
        con.executescript(main.TELEMETRY_SQL)
        con.execute("CREATE UNIQUE INDEX uq_exit_pos ON exit_log(pos_id)")
        con.execute("INSERT INTO exit_log VALUES (1791888000,'P_EXIST','TP',4100.0,4.2)")
        con.commit()
        con.close()

    @classmethod
    def tearDownClass(cls):
        os.remove(cls.db_path)

    def test_backfill_only_missing(self):
        deals = [
            _deal("P_EXIST", "DEAL_ENTRY_IN", "2026-10-13T21:46:00Z", 4096.0, 0.0),
            _deal("P_EXIST", "DEAL_ENTRY_OUT", "2026-10-14T09:00:00Z", 4100.0, 4.2),
            _deal("P_MISS", "DEAL_ENTRY_IN", "2026-10-13T22:10:00Z", 4050.0, 0.0),
            _deal("P_MISS", "DEAL_ENTRY_OUT", "2026-10-14T08:30:00Z", 4051.5, 3.0),
            _deal("P_OPEN", "DEAL_ENTRY_IN", "2026-10-14T09:10:00Z", 4010.0, 0.0),  # chưa có out-deal → bỏ qua
            _deal("P_OTHER", "DEAL_ENTRY_IN", "2026-10-14T09:11:00Z", 4011.0, 0.0, magic=999),
            _deal("P_OTHERSYM", "DEAL_ENTRY_OUT", "2026-10-14T09:12:00Z", 1.1, 2.0, symbol="EURUSDm"),
        ]

        class CStub:
            def __init__(self, ds):
                self.ds = ds

            async def get_history_deals(self, from_ts):
                return self.ds

        from datetime import datetime, timezone
        ts_open_miss = int(datetime(2026, 10, 13, 22, 10, tzinfo=timezone.utc).timestamp())
        w = DbWriter(self.db_path)
        asyncio.run(main.boot_exit_log_sync(CStub(deals), writer=w, db_path=self.db_path))
        exit_calls = [c[1] for c in w.calls if c[0] == "exit_log"]
        self.assertEqual(len(exit_calls), 1)                    # chỉ P_MISS (P_EXIST đã có row)
        self.assertEqual(exit_calls[0][0], ts_open_miss)        # ts_open P_MISS (22:10Z 13-10)
        self.assertEqual(exit_calls[0][1], "P_MISS")
        self.assertEqual(exit_calls[0][2], "EXIT_SYNC")
        self.assertAlmostEqual(exit_calls[0][3], 4051.5)        # exit_px từ out-deal
        self.assertAlmostEqual(exit_calls[0][4], 3.0)           # pnl từ profit out-deal

        # DB: P_EXIST vẫn 1 row, P_MISS đã được ghi (DbWriter INSERT OR IGNORE thật)
        con = sqlite3.connect(self.db_path)
        n = con.execute("SELECT COUNT(*) FROM exit_log WHERE pos_id='P_MISS'").fetchone()[0]
        self.assertEqual(n, 1)
        # chạy 2 lần → idempotent (P_MISS đã logged → 0 call mới; UNIQUE index chặn trùng)
        w2 = DbWriter(self.db_path)
        asyncio.run(main.boot_exit_log_sync(CStub(deals), writer=w2, db_path=self.db_path))
        self.assertEqual(w2.calls, [])                           # 0 call — không backfill lại
        n2 = con.execute("SELECT COUNT(*) FROM exit_log WHERE pos_id='P_MISS'").fetchone()[0]
        self.assertEqual(n2, 1)
        con.close()


if __name__ == "__main__":
    unittest.main()
