FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src \
    CB_CHROME_EXECUTABLE=/usr/bin/chromium \
    CB_CHROME_HTTP_PORT=9222 \
    CB_PORT=9230
WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y chromium ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cloudbrowser \
    && mkdir -p /data/profile \
    && chown -R cloudbrowser:cloudbrowser /app /data

COPY src/ /app/src/
COPY services/browser/entrypoint.py /app/services/browser/entrypoint.py
USER cloudbrowser

EXPOSE 9230
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9230/browser/health', timeout=2)"
ENTRYPOINT ["python3", "/app/services/browser/entrypoint.py"]
