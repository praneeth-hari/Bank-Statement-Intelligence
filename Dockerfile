# Bank Statement Intelligence: the API and the review UI in one image, one port.
#   docker compose up --build        then open http://localhost:8000
# Stage 1 builds the React UI; stage 2 is the Python service that also serves it.

FROM node:22-slim AS web
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
# libgomp1: onnxruntime (OCR). libgl1 and libglib2.0-0: opencv, which the OCR package installs in its non-headless form.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir ".[api,ocr]"
COPY --from=web /web/dist /app/web

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
USER app
ENV STMTAI_WEB_DIR=/app/web \
    STMTAI_DATA_DIR=/data \
    STMTAI_OCR_CACHE=/data/ocr_cache \
    STMTAI_CORS_ORIGINS="" \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "stmtai.api", "--host", "0.0.0.0", "--port", "8000"]
