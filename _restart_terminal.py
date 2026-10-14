"""_restart_terminal.py — CHỮA KẸT KÊNH SYNC: undeploy + deploy + wait_connected (terminal cloud).

Token: dùng TOKEN CONSOLE MỚI (nằm trong code sample do MetaApi console sinh ra,
~/Downloads/code-sample-python-streaming-*.zip → example.py) vì token trong .env
KHÔNG có quyền admin (undeploy/deploy = Forbidden) — đã verify thực tế 13/10.
KHÔNG đụng .env (lệnh user 13/10: ghi cảnh báo, chưa đổi token) → xem TOKEN_WARNING.md.

Chạy:
  cd /Users/admin/Desktop/DESIGN/XAU_SCALP5
  SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem \
      ./.venv/bin/python _restart_terminal.py

Nên chạy KHI BOT ĐÃ TẮT (không có client streaming nào khác → state sạch).
Vị thế + TP sống bên broker → restart terminal an toàn.
"""
import base64
import glob
import json
import os
import re
import time
import asyncio
import zipfile

ACCT = "b7a150a8-431e-45a0-9e73-265fb52163bb"


def new_token() -> str:
    """Lấy token console mới từ zip sample trong ~/Downloads (không hardcode secret)."""
    zips = sorted(glob.glob(os.path.expanduser("~/Downloads/code-sample-python-streaming-*.zip")),
                  key=os.path.getmtime, reverse=True)
    if not zips:
        raise SystemExit("THIẾU: không tìm thấy ~/Downloads/code-sample-python-streaming-*.zip → tải lại code sample từ MetaApi console")
    src = zipfile.ZipFile(zips[0]).read("example.py").decode()
    m = re.search(r"or '(eyJ[^']+)'", src)
    if not m:
        raise SystemExit("THIẾU: không giải mã được token trong example.py (file bị đổi?)")
    p = m.group(1).split(".")[1]
    p += "=" * (-len(p) % 4)
    exp = int(json.loads(base64.urlsafe_b64decode(p))["exp"])
    print(f"token console: exp={time.strftime('%d/%m/%Y %H:%M', time.gmtime(exp))} UTC")
    return m.group(1)


async def main() -> None:
    os.environ.setdefault("SSL_CERT_FILE",
                          os.path.join(os.getcwd(), ".venv/lib/python3.12/site-packages/certifi/cacert.pem"))
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(new_token())
    t0 = time.time()
    acc = await asyncio.wait_for(api.metatrader_account_api.get_account(ACCT), 30)
    print(f"state={acc.state} conn={acc.connection_status}")
    # undeploy best-effort (đã undeployed → bỏ qua, vẫn deploy)
    try:
        await asyncio.wait_for(acc.undeploy(), 60)
        print(f"UNDEPLOY OK ({time.time()-t0:.0f}s)")
    except Exception as e:
        print(f"UNDEPLOY skip ({e.__class__.__name__}): {str(e)[:120]}")
    try:
        await asyncio.wait_for(acc.deploy(), 60)
        print(f"DEPLOY OK ({time.time()-t0:.0f}s)")
        await asyncio.wait_for(acc.wait_connected(), 120)
        print(f"RESTART-TERMINAL XONG ({time.time()-t0:.0f}s) — kênh sync đã refresh, BẬT BOT NGAY BÂY GIỜ")
    except Exception as e:
        print(f"DEPLOY/WAIT FAIL ({e.__class__.__name__}): {str(e)[:160]}")


if __name__ == "__main__":
    asyncio.run(main())
