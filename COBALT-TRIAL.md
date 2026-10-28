# Cobalt trial — 2026-10-28

## Deployment

- Official Cobalt 11 container, reporting version 11.7.1.
- Upstream source commit: a636575b09de1fc55d9b8cd98cac88f5f2f16b42 (imputnet/cobalt).
- Live API: https://framesave-cobalt-api.onrender.com/
- Render service: srv-dbgue0942hec73e1ort0; free compute, Frankfurt.
- Successful deployment: dep-dbgue0h42hec73e1oth0.
- Requests require an API key held in Render environment configuration. A request without a key was rejected with error.api.auth.key.missing.
- No platform account cookies, login, configured session generator or proxy rotation.
- 30-minute duration limit; authenticated key limited to 6 requests/window and YouTube/Instagram only.

## Tests actually performed

1. GET / returned version 11.7.1 and supported services.
2. POST / for YouTube https://www.youtube.com/watch?v=aqz-KE-bpKQ with videoQuality=360, downloadMode=auto, alwaysProxy=true, localProcessing=disabled returned error.api.youtube.login. No video or audio file was obtained.
3. The same API operation for Instagram Reel https://www.instagram.com/reel/Chunk8-jurw/ returned a tunnel and filename instagram_Chunk8-jurw.jpg. Downloaded 209723 bytes; ffprobe identified a 1080x1920 JPEG (mjpeg / jpeg_pipe), not an MP4 video.
4. A second Reel https://www.instagram.com/reel/CDUMkliABpa/ returned a tunnel with filename instagram_CDUMkliABpa.jpg. This second file was not downloaded; no video success is claimed.

## Result

Cobalt is deployed and responding, but did not solve the video download requirement in these tests. FrameSave was not switched to this backend because a photo/preview must not be presented as a successful video download. No MP3 conversion from a platform was possible because no source media was obtained.

## Initial failed build

An earlier trial service framesave-cobalt (srv-dbgud36i0phs73a9kahg) attempted an upstream source build. It failed because the upstream Dockerfile copies /app/.git, absent in Render's build context. It has no successful deployment. The working trial uses Dockerfile.cobalt and the official image instead. Neither service uses paid compute.
