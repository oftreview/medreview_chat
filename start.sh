#!/bin/sh
set -e

echo "Iniciando Criatons na porta ${PORT:-8080} (gevent)"

exec gunicorn "src.app:app" --config gunicorn.conf.py
