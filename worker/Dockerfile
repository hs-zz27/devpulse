FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Share the same requirements as the backend
COPY ../backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY ../backend/app ./app

CMD ["python", "main.py"]
