"""Margin check: lý giải 'not enough money' khi test order 0.02 lot.
Chỉ đọc (RPC), không đặt lệnh.
"""
import asyncio, os
from dotenv import load_dotenv

load_dotenv()


async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(os.environ["METAAPI_TOKEN"])
    account = await asyncio.wait_for(
        api.metatrader_account_api.get_account(os.environ["ACCOUNT_ID"]), timeout=20
    )
    conn = account.get_rpc_connection()
    await asyncio.wait_for(conn.connect(), timeout=30)
    await asyncio.wait_for(conn.wait_synchronized(), timeout=120)
    info = await conn.get_account_information()
    for k in ("balance", "equity", "margin", "available", "freeMargin",
              "accountCurrency", "accountCurrencyExchangeRate", "leverage"):
        print(f"{k} = {info.get(k)}")
    for p in (await conn.get_positions() or []):
        print(f"pos {p.get('id')} side={p.get('side')} entry={p.get('openPrice')} "
              f"magic={p.get('magic')} margin={p.get('margin')} profit={p.get('profit')}")
    await conn.close()


asyncio.run(main())
