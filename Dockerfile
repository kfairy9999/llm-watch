FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY llmwatch ./llmwatch
RUN pip install --no-cache-dir .
ENV LLMWATCH_DB=/data/llmwatch.db \
    LLMWATCH_SEED=1
RUN mkdir -p /data
EXPOSE 8491
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8491/api/health')"
CMD ["llmwatch", "serve", "--host", "0.0.0.0", "--port", "8491"]
