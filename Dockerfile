FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8765 \
    SCHEMFORGE_ARTIFACTS=/app/artifacts \
    SCHEMFORGE_SHOWCASE=/app/showcase \
    SCHEMFORGE_STATIC=/app/static \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt README.md ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY static ./static
COPY showcase ./showcase
COPY examples ./examples

RUN pip install --no-cache-dir --no-deps . \
    && useradd -m -u 1000 appuser \
    && mkdir -p /app/artifacts \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8765}/healthz || exit 1

CMD ["sh", "-c", "uvicorn schemforge.server:app --host 0.0.0.0 --port ${PORT:-8765}"]
