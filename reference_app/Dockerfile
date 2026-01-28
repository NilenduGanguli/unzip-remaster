FROM python:3.11-slim-bookworm

WORKDIR /app

# Install build dependencies for uvicorn/uvloop compilation if needed & libaio for potential Oracle use
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libaio1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir uvloop httptools

COPY app ./app
COPY app_process ./app_process
COPY set_env.sh .
RUN chmod +x set_env.sh

# Run as non-root user for security (Production Grade)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

ENTRYPOINT ["./set_env.sh"]
# Environment variables should be passed by orchestrator, defaults provided in code
# Using asyncio loop because python-oracledb has compatibility issues with uvloop (setsockopt error)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "--loop", "asyncio", "--http", "httptools"]
