#!/bin/bash

# Same as launcher.sh but for the process app
IMAGE_NAME="python-unzip-process"
CONTAINER_NAME="python-unzip-process"
PORT="8080"

function show_usage {
    echo "Usage: $0 {build|up|down}"
    echo "  build : Build the Docker image"
    echo "  up    : Run the Docker container (process version)"
    echo "  down  : Stop and remove the Docker container"
}

if [ $# -eq 0 ]; then
    show_usage
    exit 1
fi

case "$1" in
    build)
        echo "Building Docker image '$IMAGE_NAME'..."
        # We use the same Dockerfile but we need to ensure it copies app_process ??
        # The Dockerfile currently says COPY app ./app
        # It needs to COPY app_process ./app_process
        # We might need to edit Dockerfile to support both or build differently.
        # Let's assume user will edit Dockerfile or we update it now to copy everything.
        docker build -t $IMAGE_NAME .
        ;;
    up)
        echo "Starting container '$CONTAINER_NAME' on port $PORT..."
        if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
            docker rm -f $CONTAINER_NAME
        fi
        
        # Create data volume or bind mount for PVC
        mkdir -p $(pwd)/unzip-pvc-data
        
        docker run -d \
            --name "$CONTAINER_NAME" \
            --network unzip-network \
            --cpus="4.0" \
            --memory="4g" \
            -p "$PORT:8080" \
            -v "$(pwd)/unzip-pvc-data:/app/unzip-pvc-data" \
            -e DB_USERNAME="system" \
            -e DB_PASSWORD="oracle" \
            -e DB_HOST="oracle-server" \
            -e DB_SERVICE="FREEPDB1" \
            -e PVC_DIR="/app/unzip-pvc-data" \
            "$IMAGE_NAME" \
            ./set_env.sh gunicorn -c app_process/gunicorn_conf.py app_process.main:app
            
            # Note: Overriding the CMD to use Gunicorn and the new app path
        ;;
    down)
        if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
            docker rm -f $CONTAINER_NAME
        fi
        ;;
    *)
        show_usage
        exit 1
        ;;
esac
