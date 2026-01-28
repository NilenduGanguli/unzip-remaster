#!/bin/bash

# Database Settings
export DB_USERNAME=${DB_USERNAME:-"unzip_user"}
export DB_PASSWORD=${DB_PASSWORD:-"YourStrong!Passw0rd"}
export DB_HOST=${DB_HOST:-"oracle-server"}
export DB_PORT=${DB_PORT:-"1521"}
export DB_SERVICE=${DB_SERVICE:-"FREEPDB1"}

# App Settings
export SERVER_PORT=${SERVER_PORT:-"8080"}
export UNZIP_UPLOAD_THREADS=${UNZIP_UPLOAD_THREADS:-"10"}

# Documentum Settings
export DOCUMENTUM_FETCH_URL=${DOCUMENTUM_FETCH_URL:-"http://documentum:8000/fetch"}
export DOCUMENTUM_UPLOAD_URL=${DOCUMENTUM_UPLOAD_URL:-"http://documentum:8000/upload"}

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

# Execute the command passed to the docker container
exec "$@"
