FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app

COPY src/ /app/src/
COPY services/browser/entrypoint.py /app/services/browser/entrypoint.py

RUN useradd --create-home --uid 10001 cloudbrowser \
    && mkdir -p /data/profile \
    && chown -R cloudbrowser:cloudbrowser /app /data
USER cloudbrowser

ENV CB_PORT=9230
EXPOSE 9230
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9230/browser/readiness', timeout=2)"
ENTRYPOINT ["python", "/app/services/browser/entrypoint.py"]
