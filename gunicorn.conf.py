"""
gunicorn.conf.py — Gunicorn configuration for Criatons.

Ensures gevent monkey patching happens before any application imports.
Gunicorn's gevent worker class handles monkey patching automatically,
but we add preload_app for faster startup and shared memory.
"""
import os

# Server
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"

# Workers — keep at 1 so in-memory debounce state is shared
workers = int(os.getenv("WORKERS", "1"))
worker_class = "gevent"
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))
timeout = 120

# Preload the app for shared memory between greenlets
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
