#!/bin/bash

# Secrets management
# In production, this might fetch from a vault or read from mounted secret files

export DB_PASSWORD=${DB_PASSWORD:-"YourStrong!Passw0rd"}
export S3_SECRET_KEY=${S3_SECRET_KEY:-"secret"}
export DOCUMENTUM_KEY_PASSWORD=${DOCUMENTUM_KEY_PASSWORD:-""}
export DOCUMENTUM_CERT_PASSWORD=${DOCUMENTUM_CERT_PASSWORD:-""}

echo "Secrets loaded."
