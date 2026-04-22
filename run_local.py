"""
run_local.py — Entry point dev para Windows (sem gunicorn).

Uso: `python run_local.py`  (ou `PORT=8081 python run_local.py`)

Por que isso existe em vez de `flask run --debug`:
- `--debug` liga o werkzeug reloader, que monitora sys.modules inteiro
  (incluindo stdlib). Um touch no mtime de tracemalloc.py ou similar
  reinicia o processo no meio do debounce do /chat, cortando a conexão
  e fazendo o browser exibir "Failed to fetch".
- threaded=False garante que gevent.spawn_later agende no mesmo hub em
  que o event.wait está rodando — senão o timer do debounce não dispara.
"""
from gevent import monkey
monkey.patch_all()

import os
from src.app import create_app

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))

if __name__ == "__main__":
    app = create_app()
    print(f"\n🟣 Closi AI dev em http://{HOST}:{PORT}\n", flush=True)
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False, threaded=False)
