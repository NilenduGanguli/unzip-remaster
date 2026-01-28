FROM python:3.11-slim-bookworm

WORKDIR /app

# Install build dependencies and system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libaio1 \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Oracle Instant Client (Required for Thick Mode, Multi-arch support)
WORKDIR /opt/oracle
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        CLIENT_ARCH="arm64"; \
    else \
        CLIENT_ARCH="x64"; \
    fi && \
    echo "Downloading Oracle Instant Client for $CLIENT_ARCH..." && \
    wget -O instantclient.zip https://download.oracle.com/otn_software/linux/instantclient/1919000/instantclient-basic-linux.$CLIENT_ARCH-19.19.0.0.0dbru.zip && \
    unzip instantclient.zip && \
    rm instantclient.zip && \
    mv instantclient_19_19 instantclient && \
    sh -c "echo /opt/oracle/instantclient > /etc/ld.so.conf.d/oracle-instantclient.conf" && \
    ldconfig

WORKDIR /app

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
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["./scripts/start_server.sh"]
