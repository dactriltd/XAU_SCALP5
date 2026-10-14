"""Symbol spec check: xác nhận margin rate XAUUSDm (lý giải 'not enough money')."""
import asyncio, os
from dotenv import load_dotenv

load_dotenv()


async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(os.environ["METAAPI_TOKEN"])
    acc = await asyncio.wait_for(
        api.metatrader_account_api.get_account(os.environ["ACCOUNT_ID"]), 20
    )
    conn = acc.get_rpc_connection()
    await asyncio.wait_for(conn.connect(), 30)
    await asyncio.wait_for(conn.wait_synchronized(), 120)
    spec = await conn.get_symbol_specification("XAUUSDm")
    for k in ("symbol", "tradeMode", "tradeAllowed", "initialMargin",
              "initialMarginC", "contractSize", "minVolume", "marketOrderVolumeMin"):
        print(f"{k} = {spec.get(k)}")
    await conn.close()


asyncio.run(main())
