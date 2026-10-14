# ⚠ TOKEN WARNING — METAAPI_TOKEN (ghi theo lệnh user, 13/10/2026 23:30)

**Quyết định của user: CHƯA ĐỔI token trong `.env`. Chỉ ghi cảnh báo.**

## Trạng thái 2 token

| Token | Ở đâu | Hạn (UTC) | Quyền | Ghi chú |
|---|---|---|---|---|
| Cũ (đang chạy) | `.env` → `METAAPI_TOKEN` | **08/01/2027** (exp=1799387874) | RPC + WS ✓, admin (undeploy/deploy/redeploy) **Forbidden** | Bot đang chạy bằng token này |
| Mới (console) | âm trong `~/Downloads/code-sample-python-streaming-*.zip → example.py` | **11/11/2026** (exp=1794463065) | RPC + WS + admin ✓ (đã verify: undeploy+deploy OK 23:18) | **CHƯA DÙNG** — chờ user xác nhận đổi |

## Vì sao tồn tại issue này
- Tối 13/10: terminal cloud MetaApi kẹt state-sync 3h+ → streaming chết.
- Chữa: `undeploy → deploy` (restart terminal) bằng **token mới** (token cũ bị Forbidden).
- Bot đã có escalation tự-chữa (redeploy khi sync kẹt) — nhưng với token cũ nó chỉ log "Forbidden — proceeding" (không self-heal thật).
- Đổi sang token mới ⇒ escalation hoạt động thật. Token mới hết hạn 11/11/2026 ⇒ phải nhắc user regenerate trước ngày đó.

## Cảnh báo runtime (đã ship code)
`main.py::warn_token_expiry()` — mỗi lần boot bot:
- decode `exp` của token `.env` (không gọi mạng),
- log INFO hạn token,
- **WARNING** khi còn ≤7 ngày, **⚠ WARNING mạnh** khi còn ≤3 ngày.

## Cập nhật 00:04 (14/10)
- **User đã cập `.env` bằng token MỚI ĐẦY ĐỦ** (exp 2027-01-11 17:01 UTC, còn ~90 ngày; rules:
  trading-account-management-api reader+writer, metaapi-rest/rpc/streaming, metastats,
  risk-management, copyfactory, mt-manager, billing) → **escalation self-heal của bot (redeploy
  khi kẹt-sync) từ đây hoạt động thật**.
- Bot LIVE 00:03:07 với token mới. Token zip 12:57 (bị 403 23:49) hết vai trò.
- `_restart_terminal.py` đã sửa: chọn zip mới nhất theo mtime (zip `-2`, 23:59).

## Tình trạng trước đó (23:49)
- Token console (trong zip sample) **bất ngờ 403 Forbidden** trên REST provisioning
  (`/users/current/accounts/...`), trong khi 23:18 nó chạy undeploy+deploy OK.
  → Nghi token bị thu hồi/phía MetaApi đổi entitlement. `_restart_terminal.py` đang CHẶM.
- **Thuốc thay thế hiện nay = bấm nút "Restart" terminal trong MetaApi web console** (user).
- Token `.env` (cũ, hạn 08/01/2027) vẫn sống bình thường (RPC sync OK 23:36) → bot vẫn trade được;
  chỉ thiếu quyền self-redeploy khi kẹt-sync.

## Hướng dẫn khi user đồng ý đổi (sau này)
1. **TỪ CONSOLE METAAPI regenerate token mới** (token trong zip 13/10 đã bị 403 từ 23:49 — đừng dùng lại).
2. Thay `METAAPI_TOKEN=` trong `XAU_SCALP5/.env` + cập nhật zip mẫu mới vào `~/Downloads` (để `_restart_terminal.py` hoạt động lại).
3. Restart bot (pattern chuẩn trong repo).
4. Kiểm tra: log dòng `[TOKEN] METAAPI_TOKEN hợp lệ đến ...` + `[METAAPI] RPC terminal connected`.

## Lưu ý an toàn
- Token = secret. File `example.py` trong Downloads chứa token mới full-access → nên xoá hoặc giữ riêng.
- Khi regenerate từ console: tạo token có quyền `trading-account-management-api` để bot tự-chữa kẹt-sync lần sau.
