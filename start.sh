#!/bin/sh
set -e

PORT=${PORT:-8080}
echo "Iniciando Criatons na porta $PORT"
exec gunicorn sandbox.app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
