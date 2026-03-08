FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE $PORT

CMD ["sh", "-c", "gunicorn sandbox.app:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120"]
