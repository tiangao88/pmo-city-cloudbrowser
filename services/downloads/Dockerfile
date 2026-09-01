FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app

COPY src/ /app/src/
COPY services/downloads/entrypoint.py /app/services/downloads/entrypoint.py

RUN useradd --create-home --uid 10001 cloudbrowser \
    && mkdir -p /data/downloads \
    && chown -R cloudbrowser:cloudbrowser /app /data
USER cloudbrowser

ENV CB_PORT=8083
EXPOSE 8083
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('CB_PORT', '8083') + '/health', timeout=2)"
ENTRYPOINT ["python", "/app/services/downloads/entrypoint.py"]
