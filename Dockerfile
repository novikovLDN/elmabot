# --- Stage 1: build the admin dashboard (React/Vite) ----------------------
FROM node:20-alpine AS dashboard-build
WORKDIR /dash
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# --- Stage 2: Python runtime (bot + web server) ---------------------------
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

# Built dashboard SPA -> served by the aiohttp server at /dashboard/.
COPY --from=dashboard-build /dash/dist ./dashboard/dist

CMD ["python", "main.py"]
