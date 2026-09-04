FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app

COPY src/ /app/src/
COPY services/cloudfiles/entrypoint.py /app/services/cloudfiles/entrypoint.py

RUN useradd --create-home --uid 10001 cloudbrowser \
    && chown -R cloudbrowser:cloudbrowser /app
USER cloudbrowser

ENV CB_PORT=8085
EXPOSE 8085
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('CB_PORT', '8085') + '/health', timeout=2)"
ENTRYPOINT ["python", "/app/services/cloudfiles/entrypoint.py"]
