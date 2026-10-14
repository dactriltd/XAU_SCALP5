"""Chạy 1-chiều: token MỚI (zip -2, tạo 23:59) → get_account + undeploy + deploy + wait.
Chữa kênh sync streaming bị kẹt. Bot hiện không cần chạm — đang retry loop."""
import base64, json, re, time, asyncio, zipfile

Z = "/Users/admin/Downloads/code-sample-python-streaming-b7a150a8-431e-45a0-9e73-265fb52163bb-2.zip"
ACCT = "b7a150a8-431e-45a0-9e73-265fb52163bb"

src = zipfile.ZipFile(Z).read("example.py").decode()
tok = re.search(r"or '(eyJ[^']+)'", src).group(1)
p = tok.split(".")[1]
p += "=" * (-len(p) % 4)
d = json.loads(base64.urlsafe_b64decode(p))
print("token MOI: iat=%s exp=%s UTC" % (
    time.strftime("%d/%m %H:%M", time.gmtime(d["iat"])),
    time.strftime("%d/%m %H:%M", time.gmtime(d["exp"]))))

async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(tok)
    t0 = time.time()
    try:
        acc = await asyncio.wait_for(api.metatrader_account_api.get_account(ACCT), 30)
        print("REST OK: state=%s conn=%s" % (acc.state, acc.connection_status))
    except Exception as e:
        print("REST FAIL (%s): %s" % (type(e).__name__, str(e)[:140]))
        return
    try:
        await asyncio.wait_for(acc.undeploy(), 60)
        print("UNDEPLOY OK (%.0fs)" % (time.time() - t0))
    except Exception as e:
        print("UNDEPLOY skip (%s): %s" % (type(e).__name__, str(e)[:100]))
    try:
        await asyncio.wait_for(acc.deploy(), 60)
        await asyncio.wait_for(acc.wait_connected(), 120)
        print("DEPLOY+WAIT OK (%.0fs) — terminal da restart, kanal sync da refresh" % (time.time() - t0))
    except Exception as e:
        print("DEPLOY/WAIT FAIL (%s): %s" % (type(e).__name__, str(e)[:140]))

asyncio.run(main())
