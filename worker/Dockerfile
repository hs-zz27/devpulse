FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend package + worker code
COPY backend /app/backend
COPY worker /app/worker

# Run worker
CMD ["python", "/app/worker/main.py"]
