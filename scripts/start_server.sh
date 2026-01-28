#!/bin/bash
set -x
set -e

pwd
ls -l scripts/
ls -l app/

echo "Initializing Unzip Service Environment..."


# 1. Set General Environment Variables
source ./scripts/set_env.sh

# 2. Set Secrets (Passwords, Keys)
source ./scripts/set_secrets.sh

# 3. Configure Certificates
source ./scripts/set_certs.sh

# 4. Start Gunicorn Server
echo "Starting Gunicorn with Uvicorn workers..."
# Ensure PYTHONPATH includes the current directory
export PYTHONPATH=$PYTHONPATH:$(pwd)
exec gunicorn -c app/core/v1/gunicorn.py app.main:app
