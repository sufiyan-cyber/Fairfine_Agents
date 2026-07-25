# FairFine backend — Cloud Run image.
FROM python:3.12-slim

# ffmpeg for frame sampling; libGL/libglib for OpenCV's runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      libgl1 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Writable paths for the SQLite ledger, sampled frames, and anything the demo
# scripts generate. `data/` is intentionally NOT copied — every file in it
# (demo clips, seed frames) is generated at runtime by scripts/, so the build
# context excludes them and the directory is simply created empty here.
#
# NOTE: Cloud Run's filesystem is ephemeral and per-instance. The ledger
# survives only for the life of a container, and two instances would keep two
# separate chains. See README "Deploy" for the production storage options.
RUN mkdir -p /app/uploads/frames /app/data/demo_clips /app/data/seed_frames

ENV DATABASE_URL=sqlite:////app/fairfine.db \
    PORT=8080

EXPOSE 8080

# Single worker: the hash chain serialises appends through an in-process lock,
# which only holds within one process.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
