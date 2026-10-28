# FrameSave

Public site: https://framesave.onrender.com/

## Status — 2026-10-28

Deployed on Render (Docker, free compute). HTTPS page and /health verified. Media downloading from the target platforms is **not operational in the tested cases**:

- YouTube test aqz-KE-bpKQ: server receives "Sign in to confirm you’re not a bot".
- Instagram test reel Chunk8-jurw: server receives "empty media response" without authorization.
- No authentication cookies, proxy rotation, CAPTCHA bypass, or DRM circumvention are used.
- 25 local automated tests passed; URL validation, private IP blocking, error responses, rate limiting and expired-file cleanup.
- Local synthetic MP4 download pipeline and MP3 conversion passed. These are not successful YouTube/Instagram download tests.
- Desktop browser page verified. Mobile browser testing not completed.

## Architecture

FastAPI serves static Russian UI and /api/info, /api/download, /api/status/{id}, /api/file/{id}. yt-dlp runs in bounded child processes, FFmpeg merges or converts local media. Node supplies yt-dlp's bundled JavaScript runtime support. Only direct public HTTP(S) formats are selected. No user credentials are stored. Each outbound Python socket destination is resolved, checked for global addresses and pinned; FFmpeg accepts only file/pipe inputs.

One application worker and replica only. Queue and ownership state are in memory. Restart invalidates jobs and session cookies and clears temporary files. Results expire after 15 minutes. Limits: 30 minutes, 300 MiB output, 5 minute processing time, 8 queued and 2 active downloads. Production scaling requires an external broker and durable state. IP rate limits use the immediate peer conservatively; per-client proxy forwarding configuration needs further verification. Job ownership uses signed session cookies independent of proxy addresses.

## Local verification

Install requirements-dev.txt and run `pytest -q`. Dockerfile binds 0.0.0.0:$PORT, default 10000, and runs a non-root user. Docker image built successfully on Render. No paid plan or additional paid resources were provisioned.
