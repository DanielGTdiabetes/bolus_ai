FROM python:3.11-slim

WORKDIR /app

ENV DATA_DIR=/tmp/data

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN mkdir -p "${DATA_DIR}"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
