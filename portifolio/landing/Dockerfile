# syntax=docker/dockerfile:1.7

# ============== Stage 1: build do bundle Astro ==============
FROM node:25-bookworm-slim AS build

ARG PUBLIC_SITE_URL=https://dsplayground.com.br
ARG PUBLIC_API_URL=https://api.dsplayground.com.br
ARG PUBLIC_PUBLISHABLE_KEY=
ARG PUBLIC_DEBUG=false

WORKDIR /app

COPY package*.json .npmrc ./

# BuildKit secret: NODE_AUTH_TOKEN (PAT GitHub com read:packages) e exposto
# apenas em /run/secrets durante este RUN — NAO entra em nenhuma layer da
# imagem final. Necessario para baixar @danpqdan/dsplayground-analytics-sdk
# do GitHub Packages registry (privado).
#
# Uso esperado:
#   export NODE_AUTH_TOKEN=$(gh auth token)
#   docker compose build --secret id=NODE_AUTH_TOKEN,env=NODE_AUTH_TOKEN landing
RUN --mount=type=secret,id=NODE_AUTH_TOKEN \
    export NODE_AUTH_TOKEN="$(cat /run/secrets/NODE_AUTH_TOKEN)" && \
    npm ci --include=dev

COPY . .

ENV PUBLIC_SITE_URL=$PUBLIC_SITE_URL \
    PUBLIC_API_URL=$PUBLIC_API_URL \
    PUBLIC_PUBLISHABLE_KEY=$PUBLIC_PUBLISHABLE_KEY \
    PUBLIC_DEBUG=$PUBLIC_DEBUG \
    NODE_ENV=production

RUN npm run build

# ============== Stage 2: runtime servindo dist/ via nginx ==============
FROM nginx:1.29-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
