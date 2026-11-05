FROM python:3.12-slim-bookworm
# The widget service (optional add-on): standard library only, nothing to install.
WORKDIR /app
COPY widget.py ./
# /data holds devices.json (paired phones, tokens stored as hashes). A new named volume copies this
# directory's owner, so the unprivileged user below can write to it.
RUN mkdir -p /data && chown 65534:65534 /data && chmod 700 /data
ENV PYTHONUNBUFFERED=1
USER 65534:65534
EXPOSE 8089
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8089/healthz', timeout=2)"
CMD ["python", "widget.py"]
