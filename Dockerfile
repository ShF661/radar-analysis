FROM python:3.12-slim

# HF Spaces runs containers as user ID 1000
RUN useradd -m -u 1000 appuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app

ENV PYTHONUNBUFFERED=1
ENV PORT=7860

EXPOSE 7860

USER appuser

CMD ["python", "-m", "app.main", "all"]
