FROM python:3.11-slim-bookworm

WORKDIR /app

# Install build dependencies and system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libaio1 \
    && rm -rf /var/lib/apt/lists/*

# Install Common Python Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Application Code
COPY app ./app
COPY scripts ./scripts

# Ensure scripts are executable
RUN chmod +x scripts/*.sh

# Create PVC directory
RUN mkdir -p unzip-pvc-data && chmod 777 unzip-pvc-data

# Run as non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 8080

ENTRYPOINT ["./scripts/start_server.sh"]
