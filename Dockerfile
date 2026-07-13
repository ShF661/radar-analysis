FROM python:3.12-slim

WORKDIR /app

# Install gmgn-cli dependency (if needed as binary, adjust accordingly)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main", "all"]
