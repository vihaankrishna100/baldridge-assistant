# The API needs a real filesystem (SQLite + the original uploaded files) and a
# long-lived process (the retrieval index is held in memory and rebuilt only on
# document change). That rules out serverless; this image runs anywhere that
# gives it a persistent volume — Railway, Render, Fly.io, or a plain VPS.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code edits don't reinstall scipy every build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Mount a volume here. Losing it means losing every account, the audit trail,
# and the document library.
ENV DATABASE_URL=sqlite:////data/baldridge.db \
    STORAGE_DIR=/data/storage
VOLUME ["/data"]

EXPOSE 8000

# Single worker on purpose: the retrieval index is per-process, so N workers
# would mean N copies of it and a rebuild storm on every upload. Scale by
# giving this one container more CPU, not more workers.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
