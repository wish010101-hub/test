FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 framesave
COPY --chown=framesave:framesave app.py security.py worker.py ./
COPY --chown=framesave:framesave static ./static
USER framesave
ENV PORT=10000 PYTHONUNBUFFERED=1 MEDIA_ROOT=/tmp/framesave
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 64 --timeout-keep-alive 5 --no-access-log"]
