# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Static frontend serving container
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

RUN printf '%s\n' \
    'server {' \
    '    listen 80;' \
    '    server_name localhost;' \
    '' \
    '    root /usr/share/nginx/html;' \
    '' \
    '    # Hashed build assets never change: cache them for a year.' \
    '    location /assets/ {' \
    '        add_header Cache-Control "public, max-age=31536000, immutable";' \
    '        try_files $uri =404;' \
    '    }' \
    '' \
    '    # The app shell must be revalidated so a rebuild is picked up on reload.' \
    '    location / {' \
    '        add_header Cache-Control "no-cache";' \
    '        index index.html index.htm;' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
