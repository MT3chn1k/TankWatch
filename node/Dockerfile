FROM python:3.12-slim-bookworm AS build
# RPi.GPIO (the DHT sensor on a Pi 3 / Pi 4) has no ready-made wheel for ARM: compile it here, so the final image
# needs no compiler
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir -w /wheels -r requirements.txt

FROM python:3.12-slim-bookworm
# libgpiod2 lets the DHT library reach the GPIO pins through /dev/gpiochip*.
RUN apt-get update && apt-get install -y --no-install-recommends libgpiod2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt && rm -rf /wheels
COPY tankwatch_node.py discovery.py ./
COPY sensors ./sensors
ENV PYTHONUNBUFFERED=1
CMD ["python", "tankwatch_node.py"]
