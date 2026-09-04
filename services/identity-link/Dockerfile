FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app

COPY src/ /app/src/
COPY services/identity-link/entrypoint.py /app/services/identity-link/entrypoint.py

RUN useradd --create-home --uid 10001 cloudbrowser \
    && mkdir -p /data \
    && chown -R cloudbrowser:cloudbrowser /app /data
USER cloudbrowser

ENV CB_PORT=8091
EXPOSE 8091
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=2)"
ENTRYPOINT ["python", "/app/services/identity-link/entrypoint.py"]
