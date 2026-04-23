# Build do Consciência Coletiva (Vite + React + pnpm) e servir com Nginx.
# Contexto de build: raiz do projeto front (onde está package.json).
#
# docker build -t consciencia-web:latest .
#
# VITE_API_BASE_URL=/ faz o frontend usar URLs relativas (/api/...)
# que o nginx do container roteia para o backend via proxy_pass.

FROM node:20-alpine AS build

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL=/
ARG VITE_INTERNAL_API_TOKEN=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_INTERNAL_API_TOKEN=$VITE_INTERNAL_API_TOKEN

RUN pnpm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
