import os
from uvicorn.workers import UvicornWorker

class AsyncioUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {"loop": "asyncio"}

# Gunicorn configuration file
# Usage: gunicorn -c app/core/v1/gunicorn.py app.main:app

bind = f"0.0.0.0:{os.getenv('SERVER_PORT', '8080')}"
workers = int(os.getenv("WORKERS", "2"))
worker_class = "app.core.v1.gunicorn.AsyncioUvicornWorker"

# Load settings to get concurrency options
# Note: We can't import app settings easily here without side effects, 
# so we rely on env vars or hard defaults matching Dockerfile.

# Timeout: Processing large zips might take time.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
# Optimized: Increased keepalive for frequent connection reuse
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "60"))

# Logging
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"  # stdout
errorlog = "-"   # stderr

# Worker configuration
# threads = 4 # Only for gthread worker, not used for uvicorn worker
