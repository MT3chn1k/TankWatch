# TankWatch display: a virtual (web) or real Unicorn HAT Mini panel, or the virtual status sign.
# Build from the repo root:  docker build -f display/Dockerfile .
# For a real Unicorn HAT Mini on a Pi, build with --build-arg HAT=1.
FROM python:3.12-slim-bookworm
ARG HAT=0
WORKDIR /app
RUN pip install --no-cache-dir pillow==11.1.0 \
 && if [ "$HAT" = 1 ]; then apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
      && pip install --no-cache-dir unicornhatmini spidev && apt-get purge -y gcc libc6-dev && rm -rf /var/lib/apt/lists/*; fi
COPY node/discovery.py node/
COPY display display
COPY sign sign
ENV PYTHONUNBUFFERED=1
CMD ["python", "display/display.py"]
