#!/usr/bin/env python3
"""S2 MIGRATION 1 LẦN (chạy khi bot STOPPED, chỉ stdlib):
  1) backup data/scalp5.db → data/sculp5.db.bak-s2-1014 (chú ý: 'sculp' typo cố ý, trùng tên file rác)
  2) dedup exit_log: giữ row ts NHỎ NHẤT mỗi pos_id (spec #16, đã duyệt) — tiebreak rowid
  3) entry_log: kiểm tra trùng → nếu có thì dedup quy tắc y hệt
  4) UNIQUE index uq_exit_pos / uq_entry_pos (căn cứ cho INSERT OR IGNORE)
  5) in bằng chứng: count trước/sau + (COUNT(*) - COUNT(DISTINCT pos_id)) phải = 0
"""
import shutil
import sqlite3
import sys
import os

DB = os.path.join("data", "scalp5.db")
BAK = os.path.join("data", "sculp5.db.bak-s2-1014")

# CTE window: giữ đúng 1 row (ts sớm nhất, tiebreak rowid sớm nhất) per pos_id
DEDUP_SQL = """
DELETE FROM {t}
WHERE rowid NOT IN (
    SELECT rowid FROM (
        SELECT rowid,
               ROW_NUMBER() OVER (PARTITION BY pos_id ORDER BY ts ASC, rowid ASC) AS rn
        FROM {t}
    ) WHERE rn = 1
)
"""


def main() -> int:
    if not os.path.exists(DB) or os.path.getsize(DB) == 0:
        print(f"[MIGRATE] FAIL: {DB} thiếu hoặc 0 byte → dừng")
        return 1
    if os.path.exists(BAK):
        print(f"[MIGRATE] FAIL: backup {BAK} đã tồn tại → KHÔNG ghi đè, kiểm tra thủ công")
        return 1

    con = sqlite3.connect(DB)
    cur = con.cursor()
    # WAL: checkpoint trước backup để file chính self-contained (bot đã stopped)
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    before = cur.execute(
        "SELECT (SELECT COUNT(*) FROM exit_log), (SELECT COUNT(*) FROM entry_log)"
    ).fetchone()
    print(f"[MIGRATE] raw-count TRƯỚC: exit_log={before[0]} · entry_log={before[1]}")

    # 1) backup
    shutil.copy2(DB, BAK)
    print(f"[MIGRATE] backup OK: {DB} → {BAK} ({os.path.getsize(BAK)} bytes)")

    # 2) dedup exit_log
    n_exit = cur.execute(DEDUP_SQL.format(t="exit_log")).rowcount
    con.commit()
    print(f"[MIGRATE] exit_log: delete {n_exit} row trùng (giữ ts nhỏ nhất/pos_id)")

    # 3) entry_log: kiểm tra trước, dedup chỉ khi có trùng
    entry_dups = cur.execute(
        "SELECT COUNT(*) FROM (SELECT pos_id FROM entry_log GROUP BY pos_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if entry_dups:
        n_entry = cur.execute(DEDUP_SQL.format(t="entry_log")).rowcount
        con.commit()
        print(f"[MIGRATE] entry_log: {entry_dups} pos_id trùng → delete {n_entry} row")
    else:
        print("[MIGRATE] entry_log: 0 pos_id trùng → không dedup")

    # 4) UNIQUE index
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_exit_pos ON exit_log(pos_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_entry_pos ON entry_log(pos_id)")
    con.commit()

    # 5) bằng chứng
    after = cur.execute(
        "SELECT (SELECT COUNT(*) FROM exit_log), (SELECT COUNT(*) FROM entry_log)"
    ).fetchone()
    diff_exit = cur.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT pos_id) FROM exit_log"
    ).fetchone()[0]
    diff_entry = cur.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT pos_id) FROM entry_log"
    ).fetchone()[0]
    idx = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%'"
    ).fetchall()
    print(f"[MIGRATE] raw-count SAU:  exit_log={after[0]} · entry_log={after[1]}")
    print(f"[MIGRATE] UNIQUE diff exit_log  = {diff_exit} (phải = 0)")
    print(f"[MIGRATE] UNIQUE diff entry_log = {diff_entry} (phải = 0)")
    print(f"[MIGRATE] index: {[r[0] for r in idx]}")
    con.close()

    ok = diff_exit == 0 and diff_entry == 0 and len(idx) == 2
    print("[MIGRATE] " + ("OK ✅" if ok else "FAIL ❌ (thiếu index hoặc còn trùng)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
