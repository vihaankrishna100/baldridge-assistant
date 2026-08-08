# Cloud Run image.
#
# With REPO_BACKEND=firestore there is no local state to preserve: accounts,
# documents and chunks live in Firestore, originals in Cloud Storage. That is
# what makes a scale-to-zero container acceptable here.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV REPO_BACKEND=firestore

# Cloud Run injects PORT. One worker on purpose: the retrieval index is held in
# this process's memory, so a second worker would mean a second copy of it and
# a second rebuild on every cold start. Scale with instances, not workers.
#
# --timeout-keep-alive is raised because answers stream token by token and an
# idle-looking connection during a long generation must not be dropped.
CMD exec uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8080} \
    --workers 1 \
    --timeout-keep-alive 120 \
    --proxy-headers \
    --forwarded-allow-ips='*'
