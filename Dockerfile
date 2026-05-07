# syntax=docker/dockerfile:1.7

# ============== Stage 1: build do bundle Astro ==============
FROM node:22-bookworm-slim AS build

ARG PUBLIC_SITE_URL=https://dsplayground.com.br
ARG PUBLIC_API_URL=https://api.dsplayground.com.br
ARG PUBLIC_PUBLISHABLE_KEY=
ARG PUBLIC_DEBUG=false

WORKDIR /app

COPY package*.json .npmrc ./

RUN npm ci --include=dev

COPY . .

ENV PUBLIC_SITE_URL=$PUBLIC_SITE_URL \
    PUBLIC_API_URL=$PUBLIC_API_URL \
    PUBLIC_PUBLISHABLE_KEY=$PUBLIC_PUBLISHABLE_KEY \
    PUBLIC_DEBUG=$PUBLIC_DEBUG \
    NODE_ENV=production

RUN npm run build

# ============== Stage 2: runtime servindo dist/ via nginx ==============
FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
