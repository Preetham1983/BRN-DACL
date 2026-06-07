# ──────────────────────────────────────────────
# DACL Agent — Frontend (React + Vite → Nginx)
# ──────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first (layer-cached unless package.json changes)
COPY package.json ./
RUN npm install

# Copy source and build
COPY . .
RUN npm run build
# Output: /app/dist

# ── Stage 2: Serve with Nginx ─────────────────
FROM nginx:1.27-alpine

# Copy Vite build output
COPY --from=builder /app/dist /usr/share/nginx/html

# Replace default nginx config with SPA-aware config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
