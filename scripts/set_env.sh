#!/bin/bash

# Database Settings
export DB_USERNAME=${DB_USERNAME:-"unzip_user"}
export DB_PASSWORD=${DB_PASSWORD:-"YourStrong!Passw0rd"}
export DB_HOST=${DB_HOST:-"oracle-server"}
export DB_PORT=${DB_PORT:-"1521"}
export DB_SERVICE=${DB_SERVICE:-"FREEPDB1"}

# Database Pool Settings
export DB_POOL_SIZE=${DB_POOL_SIZE:-"10"}
export DB_MAX_OVERFLOW=${DB_MAX_OVERFLOW:-"10"}
export DB_POOL_RECYCLE=${DB_POOL_RECYCLE:-"3600"}
export DB_THICK_MODE=${DB_THICK_MODE:-"false"}

# App Settings
export APP_NAME=${APP_NAME:-"Unzip Service"}
export APP_VERSION=${APP_VERSION:-"1.0.0"}
export APP_REGION=${APP_REGION:-"nam"}
export DEBUG_MODE=${DEBUG_MODE:-"false"}
export DEV_MODE=${DEV_MODE:-"false"}
export VER_NUM=${VER_NUM:-"8"}
export PVC_DIR=${PVC_DIR:-"./unzip-pvc-data"}
export SERVER_PORT=${SERVER_PORT:-"8080"}
export UNZIP_UPLOAD_THREADS=${UNZIP_UPLOAD_THREADS:-"10"}
export UNZIP_MAX_WORKERS=${UNZIP_MAX_WORKERS:-"4"}
export UNZIP_ENABLE_CACHE=${UNZIP_ENABLE_CACHE:-"false"}

# S3 Settings
export S3_BUCKET_NAME=${S3_BUCKET_NAME:-"unzip-documents"}
export S3_HOST=${S3_HOST:-"http://s3-server:9000"}
export S3_ACCESS_KEY=${S3_ACCESS_KEY:-"unzip_user"}
export S3_KEY_PREFIX=${S3_KEY_PREFIX:-"UNZIP"}
# S3_SECRET_KEY is handled in set_secrets.sh

# Gunicorn Settings
export WORKERS=${WORKERS:-"2"}
export GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-"120"}
export GUNICORN_KEEPALIVE=${GUNICORN_KEEPALIVE:-"5"}
export GUNICORN_LOG_LEVEL=${GUNICORN_LOG_LEVEL:-"info"}

# Documentum Settings
export DOCUMENTUM_FETCH_URL=${DOCUMENTUM_FETCH_URL:-"http://documentum:8000/fetch"}
export DOCUMENTUM_UPLOAD_URL=${DOCUMENTUM_UPLOAD_URL:-"http://documentum:8000/upload"}
export DOCUMENTUM_TIMEOUT=${DOCUMENTUM_TIMEOUT:-"30.0"}
export DOCUMENTUM_MAX_CONNECTIONS=${DOCUMENTUM_MAX_CONNECTIONS:-"100"}
export DOCUMENTUM_MAX_KEEPALIVE=${DOCUMENTUM_MAX_KEEPALIVE:-"50"}

# Helper Services
export FILE_HANDLER_SERVICE_URL=${FILE_HANDLER_SERVICE_URL:-"http://document-handler:8080/upload/pvc/files"}

# Cert Settings
export USE_CERT=${USE_CERT:-"false"}
export DOCUMENTUM_CERT_PATH=${DOCUMENTUM_CERT_PATH:-""}
export DOCUMENTUM_KEY_PATH=${DOCUMENTUM_KEY_PATH:-""}
# export DOCUMENTUM_KEY_PASSWORD=${DOCUMENTUM_KEY_PASSWORD:-""}
export DOCUMENTUM_P12_PATH=${DOCUMENTUM_P12_PATH:-""}
export DOCUMENTUM_CERT_PASSWORD=${DOCUMENTUM_CERT_PASSWORD:-""}

if [ "$USE_CERT" = "true" ]; then
    if [ -n "$DOCUMENTUM_CERT_PATH" ] && [ -f "$DOCUMENTUM_CERT_PATH" ]; then
         echo "Verified Certificate: $DOCUMENTUM_CERT_PATH"
    else
         echo "USE_CERT is true but DOCUMENTUM_CERT_PATH is invalid: $DOCUMENTUM_CERT_PATH"
         exit 1
    fi
    
    if [ -n "$DOCUMENTUM_KEY_PATH" ] && [ -f "$DOCUMENTUM_KEY_PATH" ]; then
         echo "Verified Key: $DOCUMENTUM_KEY_PATH"
    else
         echo "USE_CERT is true but DOCUMENTUM_KEY_PATH is invalid: $DOCUMENTUM_KEY_PATH"
         exit 1
    fi
fi

echo "Environment variables set from set_env.sh:"
echo "DB_HOST: $DB_HOST"
echo "DB_SERVICE: $DB_SERVICE"
echo "SERVER_PORT: $SERVER_PORT"
# Don't echo passwords
