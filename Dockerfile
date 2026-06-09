FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Node.js is required by the Incy crypt-link sidecar (scripts/incy_encode.mjs,
# which uses @incy/link-encoder). Without it the "Открыть в Incy" button is just
# hidden — the bot still runs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY . .

CMD ["python", "main.py"]
