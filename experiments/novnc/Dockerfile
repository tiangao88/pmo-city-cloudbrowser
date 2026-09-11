FROM debian:bookworm-slim
RUN apt-get update && apt-get install --no-install-recommends -y \
    chromium ca-certificates python3 xvfb x11vnc novnc websockify x11-utils \
    && useradd --create-home --uid 10001 cloudbrowser
WORKDIR /app
COPY src/ /app/src/
COPY experiments/novnc/ /app/experiment/
ENV PYTHONPATH=/app/src DISPLAY=:99 PYTHONUNBUFFERED=1
USER 10001
EXPOSE 6080
ENTRYPOINT ["python3", "/app/experiment/run.py"]
