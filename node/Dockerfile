FROM python:3.12-slim-bookworm
# libgpiod2 lets the DHT library reach the GPIO pins through /dev/gpiochip*.
RUN apt-get update && apt-get install -y --no-install-recommends libgpiod2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tankwatch_node.py discovery.py ./
COPY sensors ./sensors
ENV PYTHONUNBUFFERED=1
CMD ["python", "tankwatch_node.py"]
