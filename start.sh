#!/bin/sh
set -e

PORT=${PORT:-8080}

# Número de workers gevent (processos). Mantenha em 1 para que o estado
# de debounce in-memory seja compartilhado entre todas as conexões.
# O gevent cobre a concorrência com greenlets, não com processos.
WORKERS=${WORKERS:-1}

# Máximo de conexões simultâneas por worker.
# Com gevent, cada conexão é um greenlet leve (~100KB RAM).
# 1000 greenlets = ~100MB — confortável para 500 leads/dia.
WORKER_CONNECTIONS=${WORKER_CONNECTIONS:-1000}

echo "Iniciando Criatons na porta $PORT (gevent, ${WORKERS}w × ${WORKER_CONNECTIONS} conn)"

exec gunicorn sandbox.app:app \
  --bind "0.0.0.0:$PORT" \
  --worker-class gevent \
  --workers "$WORKERS" \
  --worker-connections "$WORKER_CONNECTIONS" \
  --timeout 120
