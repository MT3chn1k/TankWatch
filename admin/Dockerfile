FROM python:3.12-slim-bookworm
# The admin page: standard library only, nothing to install.
WORKDIR /app
COPY admin.py index.html admin.js admin.css icon.png ./
ENV PYTHONUNBUFFERED=1
USER 65534:65534
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=2)"
CMD ["python", "admin.py"]
