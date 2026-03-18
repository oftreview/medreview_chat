#!/bin/sh
set -e

echo "Iniciando Closi AI na porta ${PORT:-8080} (gevent)"

exec gunicorn "src.app:app" --config gunicorn.conf.py
