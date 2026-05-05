# syntax=docker/dockerfile:1.7

# ============== Stage 1: build do bundle Vite ==============
FROM node:25-bookworm-slim AS build

ARG VITE_API_URL=http://localhost:5000
ARG VITE_WEBSOCKET_URL=http://localhost:5000
ARG VITE_DEBUG=false
ARG VITE_PUBLISHABLE_KEY=

WORKDIR /app

COPY package*.json .npmrc ./
# npm ci com NODE_ENV=production pula devDependencies (incluindo o Vite).
# Instalamos tudo, rodamos o build e so depois setamos o mode de producao.
#
# BuildKit secret: NODE_AUTH_TOKEN (PAT GitHub com read:packages) e exposto
# apenas em /run/secrets durante este RUN — NAO entra em nenhuma layer da
# imagem final. Necessario para baixar @danpqdan/dsplayground-analytics-sdk
# do GitHub Packages registry (privado).
#
# Uso esperado:
#   export NODE_AUTH_TOKEN=$(gh auth token)
#   docker compose build --secret id=NODE_AUTH_TOKEN,env=NODE_AUTH_TOKEN frontend
# Em CI o token vem de secrets.GITHUB_TOKEN (built-in com read:packages).
RUN --mount=type=secret,id=NODE_AUTH_TOKEN \
    export NODE_AUTH_TOKEN="$(cat /run/secrets/NODE_AUTH_TOKEN)" && \
    npm ci --include=dev

COPY . .

ENV VITE_API_URL=$VITE_API_URL \
    VITE_WEBSOCKET_URL=$VITE_WEBSOCKET_URL \
    VITE_DEBUG=$VITE_DEBUG \
    VITE_PUBLISHABLE_KEY=$VITE_PUBLISHABLE_KEY \
    NODE_ENV=production

RUN npm run build

# ============== Stage 2: runtime servindo dist/ via nginx ==============
FROM nginx:1.29-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
