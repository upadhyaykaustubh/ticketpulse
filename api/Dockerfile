FROM python:3.11-slim

# 1. Optimize Python runtime for containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 2. Install curl for Docker health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Leverage Docker Layer Caching for dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy source code
COPY . .

# 5. Security: Run as non-root user
RUN useradd -u 1001 -m appuser && chown -R appuser:appuser /app
USER 1001

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
