FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY src/ /app/src/
COPY services/agent-control/entrypoint.py /app/services/agent-control/entrypoint.py

RUN useradd --create-home --uid 10001 cloudbrowser
ENV PYTHONPATH=/app/src
ENV CB_PORT=8090
USER cloudbrowser
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('CB_PORT', '8090') + '/health', timeout=2)"
ENTRYPOINT ["python", "/app/services/agent-control/entrypoint.py"]
