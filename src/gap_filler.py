#!/usr/bin/env python3
"""XAU_SCALP5 — M1 Candle Gap Filler (async).

Phát hiện nến M1 bị thiếu trong DB, loại bỏ weekend/holiday gaps (market closed),
fetch historical M1 candles từ MetaAPI để fill các gap trong giờ giao dịch.

Usage:
    SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem \
    python -m src.gap_filler --check --days 14      # chỉ kiểm tra
    SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem \
    python -m src.gap_filler --fill --days 14       # fill gaps (rate-limited)
"""
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple, Optional

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.metaapi_client import MetaAPIClient
from src.storage import SQLiteStorage, get_storage
from src.models import Timeframe
from src.config import SYMBOL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("GAP_FILLER")


class M1GapFiller:
    """Fill M1 candle gaps in DB using MetaAPI historical data."""

    def __init__(self, metaapi: MetaAPIClient, storage: SQLiteStorage):
        self.metaapi = metaapi
        self.storage = storage
        self.symbol = SYMBOL
        self.timeframe = Timeframe.M1
        self.interval_sec = 60

    def is_weekend_gap(self, start_ts: int, end_ts: int) -> bool:
        """Check if gap is entirely within weekend (market closed).
        
        XAUUSD trades 24/5. Market closed:
        - Friday 21:00 UTC -> Sunday 22:00 UTC
        """
        for ts in range(start_ts, end_ts + 1, self.interval_sec):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            wd = dt.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
            hour = dt.hour

            # Market open: Sun 22:00 -> Fri 21:00
            if wd == 6 and hour < 22:  # Sunday before 22:00
                continue  # market closed
            if wd == 4 and hour >= 21:  # Friday 21:00+
                continue  # market closed
            if wd == 5:  # Saturday all day
                continue  # market closed

            # Found a timestamp that should have market data
            return False

        return True  # All timestamps in gap are weekend/closed

    async def find_m1_gaps(self, lookback_days: int = 14) -> List[Tuple[int, int]]:
        """Find M1 candle gaps in DB within lookback_days.

        Returns list of (start_ts, end_ts) for missing ranges.
        Only returns gaps that are NOT weekend gaps.
        """
        now = int(time.time())
        cutoff = now - (lookback_days * 86400)

        # Get all M1 timestamps in range using storage
        cursor = await self.storage._pool.execute(
            "SELECT timestamp FROM candles WHERE symbol=? AND timeframe=? AND timestamp >= ? ORDER BY timestamp",
            (self.symbol, self.timeframe.value, cutoff)
        )
        rows = await cursor.fetchall()
        timestamps = [row[0] for row in rows]

        if not timestamps:
            log.warning("No M1 candles in DB")
            return []

        # Find gaps > 1 interval
        gaps = []
        for i in range(1, len(timestamps)):
            prev_ts = timestamps[i - 1]
            curr_ts = timestamps[i]
            expected_diff = self.interval_sec
            actual_diff = curr_ts - prev_ts

            if actual_diff > expected_diff * 1.5:  # gap > 1.5 min
                missing_start = prev_ts + expected_diff
                missing_end = curr_ts - expected_diff
                missing_count = (missing_end - missing_start) // expected_diff + 1

                # Check if this is a weekend gap
                if self.is_weekend_gap(missing_start, missing_end):
                    log.info(f"Skipping weekend gap: {datetime.fromtimestamp(missing_start, tz=timezone.utc)} -> {datetime.fromtimestamp(missing_end, tz=timezone.utc)} ({missing_count} candles)")
                    continue

                gaps.append((missing_start, missing_end))
                log.info(f"Gap found: {datetime.fromtimestamp(missing_start, tz=timezone.utc)} -> {datetime.fromtimestamp(missing_end, tz=timezone.utc)} ({missing_count} candles)")

        # Also check tail gap (last candle to now)
        last_ts = timestamps[-1]
        if now - last_ts > self.interval_sec * 1.5:
            missing_start = last_ts + self.interval_sec
            missing_end = now - (now % self.interval_sec)  # last closed minute
            missing_count = (missing_end - missing_start) // self.interval_sec + 1

            if not self.is_weekend_gap(missing_start, missing_end):
                gaps.append((missing_start, missing_end))
                log.info(f"Tail gap: {datetime.fromtimestamp(missing_start, tz=timezone.utc)} -> {datetime.fromtimestamp(missing_end, tz=timezone.utc)} ({missing_count} candles)")
            else:
                log.info(f"Skipping weekend tail gap: {datetime.fromtimestamp(missing_start, tz=timezone.utc)} -> {datetime.fromtimestamp(missing_end, tz=timezone.utc)}")

        return gaps

    async def fill_gap(self, start_ts: int, end_ts: int, max_candles_per_call: int = 1000) -> int:
        """Fill a single gap by fetching historical candles.

        MetaAPI fetches BACKWARDS from start_time (most recent first).
        So we fetch from end_ts backwards in chunks.
        """
        total_filled = 0
        current_end = end_ts

        while current_end >= start_ts:
            # Calculate how many candles we need
            remaining = (current_end - start_ts) // self.interval_sec + 1
            limit = min(max_candles_per_call, remaining)

            # Fetch candles ending at current_end (MetaAPI uses start_time as the END of range)
            start_time = datetime.fromtimestamp(current_end, tz=timezone.utc)

            log.info(f"  Fetching {limit} candles ending at {start_time}...")
            candles = await self.metaapi.fetch_candles(
                self.symbol,
                self.timeframe,
                limit=limit,
                start_time=start_time
            )

            if not candles:
                log.warning(f"  No candles returned for {start_time}, stopping gap fill")
                break

            # Filter to only candles within our gap range
            gap_candles = [c for c in candles if start_ts <= int(c.timestamp.timestamp()) <= current_end]

            if not gap_candles:
                log.warning(f"  No candles in gap range, stopping")
                break

            # Insert
            await self.storage.insert_candles_batch(gap_candles)
            filled = len(gap_candles)
            total_filled += filled
            log.info(f"  Inserted {filled} candles (total this gap: {total_filled})")

            # Move to next chunk (older candles)
            oldest_ts = min(int(c.timestamp.timestamp()) for c in gap_candles)
            current_end = oldest_ts - self.interval_sec

            # Rate limit
            await asyncio.sleep(2.0)

        return total_filled

    async def fill_all_gaps(self, lookback_days: int = 14, max_total_candles: int = 10000) -> int:
        """Find and fill all non-weekend gaps."""
        gaps = await self.find_m1_gaps(lookback_days)

        if not gaps:
            log.info("No fillable gaps found")
            return 0

        log.info(f"Found {len(gaps)} fillable gaps")

        total_filled = 0
        for start_ts, end_ts in gaps:
            if total_filled >= max_total_candles:
                log.warning(f"Reached max_total_candles ({max_total_candles}), stopping")
                break

            remaining_budget = max_total_candles - total_filled
            log.info(f"Filling gap: {datetime.fromtimestamp(start_ts, tz=timezone.utc)} -> {datetime.fromtimestamp(end_ts, tz=timezone.utc)} (budget: {remaining_budget})")

            filled = await self.fill_gap(start_ts, end_ts)
            total_filled += filled

            if filled == 0:
                log.warning(f"Gap fill returned 0, continuing to next gap")

        log.info(f"Gap filling complete. Total candles inserted: {total_filled}")
        return total_filled


async def main():
    parser = argparse.ArgumentParser(description="M1 Candle Gap Filler for XAU_SCALP5")
    parser.add_argument("--check", action="store_true", help="Only check for gaps, don't fill")
    parser.add_argument("--fill", action="store_true", help="Fill gaps")
    parser.add_argument("--days", type=int, default=14, help="Lookback days for gap detection")
    parser.add_argument("--max-candles", type=int, default=10000, help="Max candles to fetch total")
    args = parser.parse_args()

    if not args.check and not args.fill:
        parser.error("Must specify --check or --fill")

    # Load env
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.getcwd(), ".env"))

    token = os.environ.get("METAAPI_TOKEN", "")
    account = os.environ.get("ACCOUNT_ID", "")
    if not token or "your_" in token or not account:
        log.error("METAAPI_TOKEN/ACCOUNT_ID not configured")
        return 1

    # Initialize MetaAPI client
    storage = await get_storage("data/scalp5.db")
    client = MetaAPIClient(token, account, storage)

    if not await client.initialize():
        log.error("MetaAPI initialization failed")
        return 1

    filler = M1GapFiller(client, storage)

    if args.check:
        gaps = await filler.find_m1_gaps(args.days)
        if gaps:
            total_missing = sum((end - start) // 60 + 1 for start, end in gaps)
            print(f"\nFound {len(gaps)} fillable gaps, {total_missing} missing candles:")
            for start, end in gaps:
                cnt = (end - start) // 60 + 1
                print(f"  {datetime.fromtimestamp(start, tz=timezone.utc)} -> {datetime.fromtimestamp(end, tz=timezone.utc)} ({cnt} candles)")
        else:
            print("No fillable gaps found")
        await client.shutdown()
        return 0

    if args.fill:
        total = await filler.fill_all_gaps(args.days, args.max_candles)
        await client.shutdown()
        print(f"\nDone. Filled {total} candles.")
        return 0


if __name__ == "__main__":
    asyncio.run(main())