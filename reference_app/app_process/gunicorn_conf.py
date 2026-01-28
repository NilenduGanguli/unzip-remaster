import os

# Gunicorn configuration file
# Usage: gunicorn -c app_process/gunicorn_conf.py app_process.main:app

bind = f"0.0.0.0:{os.getenv('SERVER_PORT', '8080')}"
workers = int(os.getenv("WORKERS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"

# Load settings to get concurrency options
# Note: We can't import app settings easily here without side effects, 
# so we rely on env vars or hard defaults matching Dockerfile.

# Timeout: Processing large zips might take time.
timeout = 120 
keepalive = 5

# Logging
loglevel = "info"
accesslog = "-"  # stdout
errorlog = "-"   # stderr

# Worker configuration
# threads = 4 # Only for gthread worker, not used for uvicorn worker
