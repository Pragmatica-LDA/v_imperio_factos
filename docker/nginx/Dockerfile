# Entrada pública (Coolify): build do React servido pelo nginx + proxy para o Django.
# Build context: raiz do repositório.
FROM node:24.21.0-trixie-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry https://registry.npmjs.org --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM nginx:1.29-alpine
COPY docker/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
