# LESSONS.md — Bài học sự cố & kỹ thuật (SOT)

> Mỗi bài = Hiện tượng → Root cause → **QUY TẮC** (bắt buộc cho các lần sau).
> Nguồn: sự cố MetaApi 14/10 + fix probe sample + 3-patch main.py (WCH/LVL/H4).

---

## L1. Provider-side failure ≠ client-side failure (sự cố MetaApi 14/10 10:20)

- **Hiện tượng**: `Connection refused by the server` (WS london:0/1) + RPC sync timeout — trông giống lỗi code bên ta.
- **Root cause**: cloud terminal MetaApi mất liên kết broker (Exness-MT5Trial7). Bằng chứng: cùng máy + cùng code + cùng token chạy tốt 08:02; REST sống; gateway flapping (curl 22:2x: HTTP 200 + sid, nhưng engineio vẫn refused lúc response = None).
- **QUY TẮC**: Trước khi đụng code, chứng minh 3 lớp: (a) state cũ chạy OK ở đâu/ lúc nào · (b) REST/token sống? · (c) client khác cùng account cũng fail? Provider-side **không chữa được bằng client code** — client code chỉ làm được 3 việc: robust (bounded waits + backoff + không churn) · self-heal khi provider hồi · escalate (redeploy ≤1/chu kỳ — ⚠ docs: mỗi lần start server = **6h phí** · support ticket khi sự cố > SLA 99.5%).

## L2. Connection churn = silent rate-limit amplifier (WCH)

- **Hiện tượng**: mỗi chu kỳ StreamStalled tạo client MetaApi MỚI (2 WS + 1 RPC) trong khi client cũ chưa đóng → server load + rủi ro rate-limit + churn chính là anti-pattern MetaApi docs cấm ("rapid connect/disconnect cycles").
- **Root cause**: path exception `raise StreamStalled()` (main.py ORDER BOOT) bỏ qua `client.shutdown()` (shutdown chỉ ở normal-exit).
- **QUY TẮC**: **Mọi path tạo client MetaApi mới PHẢI close client cũ trước** (pattern WCH; tham chiếu design: `kim_long_bot reinitialize()` L105-127 — close RPC+stream cũ rồi build mới). Đã fix main.py ~L294-299 (try/except best-effort trước raise).

## L3. Fail-open "nuốt" bug = silent degradation (LVL threading)

- **Hiện tượng**: bot "chạy bình thường" nhưng **G2-LVL + R1/R2 (bộ lọc entry strategy V2) tắt im lặng trong nhiều giờ** — 4 dòng `ProgrammingError: SQLite objects created in a thread` (log 19:37→21:27, mọi boot).
- **Root cause**: truyền `db._conn` (conn được tạo trong worker-thread của aiosqlite) vào hàm **đồng bộ** `_lvl.rebuild_from_candles/on_m1_close` gọi từ luồng chính → Python sqlite3 cấm dùng cross-thread. catch-exception + log.warning = "chưa crash" → không ai cảnh giác.
- **QUY TẮC**: (a) KHÔNG ĐƯỢC truyền async/worker-thread object vào code sync — mở `sqlite3.connect(DB_PATH)` sync riêng (DB là WAL-mode → 2 conn chung sống an toàn). Đã fix main.py 2 call-site. (b) **Feature bị fail-open tắt = ghi tác động KPI vào STATE.md** (G2-LVL OFF = chất lượng entry giảm, không chỉ "log warning cho qua").

## L4. DB-first, RPC-last (H4 warmup)

- **Hiện tượng**: warmup LUÔN fetch M1 qua mạng (`fetch_candles`) dù SQLite đã có sẵn (M1GapFiller lấp từ trước) — tốn CPU-credit + rủi ro 429 ngay bước khởi động, đúng lúc WS đang đứt.
- **QUY TẮC**: đọc cache local (SQLite) trước; chỉ gọi mạng khi dữ liệu thiếu (threshold <30 nến). Đã fix nhánh `LADDER_TF == "M1"` (limit giữ S1_SWINGS=600). Kèm: mọi historical call qua throttle ≥5s + tôn `recommendedRetryTime` (cap 120s) — ORDER BOOT 21:4x đã làm, probe fix F3 áp cùng chuẩn.

## L5. Code sample "chính chủ" không phải là reference implementation (MetaApi sample)

- **Hiện tượng**: sample streaming chính thức MetaApi (Downloads -3.zip) có đủ defect: waits **vô hạn** (hang ngay khi cloud down — đúng sự cố 14/10) · đặt **lệnh thật GBPUSD không điều kiện** · **token nhúng trong file** · 6+ historical calls không throttle · không `close()` SDK · không signal handling.
- **QUY TẮC**: dùng bất kỳ sample nào: (1) tắt/no-gate lệnh thật · (2) bound mọi waits · (3) throttle + tôn 429 · (4) 1 SDK instance + close() đúng · (5) secrets chỉ qua env · (6) UTC-aware · (7) SIGINT/SIGTERM. Bản sống: `scripts/metaapi_probe_resilient.py` (F1–F9, py_compile OK, chưa chạy — chạy = CHỜ NGƯỜI vì mở client thứ 2 cạnh tranh bot).

## L6. Process: L1/L2 + verifier + anti-loop (AGENTS.md mới "Opencode Minimal Loop")

- **Hiện tượng 14/10**: sửa code giữa phiên + restart liên tục + nhiều client song song → burn chu kỳ + churn.
- **QUY TẮC**: L1 = report-only; code change = L2 (human bật) + worktree (deviation phải ghi STATE.md — work-order user hôm nay = in-place, đã ghi) + **verifier verdict trước restart** (hôm nay: APPROVE 5/5) + max 3 fix-attempt/item rồi escalate · baseline trước optimization · mọi claim có evidence (log/metric), cấm "có vẻ như…".

---

| Bài | Áp dụng ngày | File liên quan |
|-----|--------------|----------------|
| L1-L2 | 14/10 22:5x | `main.py` WCH ~L294-299 · escalation redeploy (≤1/cycle, cross-cycle ≥10′) |
| L3-L4 | 14/10 22:5x | `main.py` LVL ~L326/~L411 · warmup ~L372-375 |
| L5 | 14/10 22:4x | `scripts/metaapi_probe_resilient.py` |
| L6 | 14/10 22:4x+ | `AGENTS.md` (Opencode Minimal Loop) · STATE.md run log |
