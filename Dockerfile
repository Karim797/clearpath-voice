FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ENVIRONMENT=production
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN base64 -d runtime_bundle.tar.gz.b64 > /tmp/runtime_bundle.tar.gz \
    && tar xzf /tmp/runtime_bundle.tar.gz -C /app \
    && rm -f /tmp/runtime_bundle.tar.gz runtime_bundle.tar.gz.b64
EXPOSE 8000
CMD ["sh", "-c", "python -m scripts.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
