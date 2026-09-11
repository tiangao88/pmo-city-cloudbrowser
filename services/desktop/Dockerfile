# Candidate only: not referenced by release Compose or deployment automation.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install --no-install-recommends -y \
    chromium ca-certificates python3 xvfb x11vnc novnc websockify x11-utils libxtst6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 cloudbrowser \
    && mkdir -p /data/profile /data/downloads-browser \
    && chown -R cloudbrowser:cloudbrowser /data
# Debian's websockify belongs to system Python 3.11. Install the transport for
# the actual Python 3.12 entrypoint; never import another interpreter's packages.
RUN python -m pip install --no-cache-dir websockify==0.10.0
WORKDIR /app
COPY src/ /app/src/
ENV PYTHONPATH=/app/src DISPLAY=:99 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CB_CHROME_EXECUTABLE=/usr/bin/chromium CB_CHROME_HTTP_PORT=9222 CB_PORT=9230 \
    CB_BROWSER_AUTOSTART=0
ENV CB_CHROME_EXTRA_ARGS="--no-sandbox --disable-gpu --disable-dev-shm-usage --window-size=1280,800"
USER 10001
# 9230 and 6083 are private control-plane ports. Only 8082 reaches the SSO edge.
EXPOSE 8082 9230 6083
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9230/browser/health', timeout=2)"
ENTRYPOINT ["python3", "-m", "cloudbrowser.viewer.desktop_runtime"]
