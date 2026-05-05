# Nginx

Proxy reverso publico. Fronteira entre Cloudflare e os containers do stack. Responsavel por TLS com cert do Cloudflare Origin, encaminhamento por hostname, upgrade de WebSocket (Socket.IO) e rate limit de borda.

## Arquivos

- `portifolio.conf` — **referencia historica**. Arquivo real em prod e renderizado pela role Ansible `nginx` a partir de `ark/ansible/roles/nginx/templates/portifolio.conf.j2`. Manter este `.conf` como espelho do template.
- `portifolio.monitoring.conf` — vhosts de Grafana (`grafana.*`) e InfluxDB (`influx.*`).
- `ssl.conf` — snippet de hardening TLS (TLS 1.2+, ciphers modernos). OCSP stapling fica ignorado porque o CF Origin CA nao e publico (warning benigno).

## Deploy

Layout Rocky/RHEL: configs ficam em **`/etc/nginx/conf.d/*.conf`** (nao `sites-available`). Instalacao via role Ansible `nginx` (`ark/ansible/roles/nginx`). O template renderizado substitui o arquivo vivo, e o handler faz reload com `nginx -t` antes.

Cert: **Cloudflare Origin Certificate** em `/etc/ssl/cloudflare-origin/` (ver `ark/docs/servidor-producao.md` secao "TLS"). A task certbot legada na role e no-op por causa de `creates:` apontando pro cert antigo — limpar quando houver janela.

## Topologia de vhosts

```
dsplayground.com.br                             → 127.0.0.1:3000   (frontend Vite)
dsplayground.com.br/api/cliente/auth/*          → 127.0.0.1:5000   (backend — auth do dashboard)
dsplayground.com.br/cliente/metricas/*          → 127.0.0.1:3001   (Grafana via auth_request)
api.dsplayground.com.br                         → 127.0.0.1:5000   (backend Flask + Socket.IO)
grafana.dsplayground.com.br                     → 127.0.0.1:3001   (admin direto, fora do auth.proxy)
influx.dsplayground.com.br                      → 127.0.0.1:8086
```

Todos os upstreams bindam so em loopback no host — o Nginx e o unico caminho publico.

## Pontos chave

- **WebSocket**: `proxy_set_header Upgrade` + `Connection "upgrade"` em todos os vhosts. Socket.IO sobe em `wss://api.dsplayground.com.br/api/socket.io/` — path canonico em todos os ambientes (definido em `backend/app.py` `socketio_config['path']`, fora do bloco condicional de env). `async_mode='eventlet'` sempre — sem isso o handshake retorna `upgrades:[]` e o cliente cicla em polling.
- **IP real**: `X-Forwarded-For` e `X-Real-IP` sao passados ao backend. Como o trafego passa primeiro pelo CF, o `X-Forwarded-For` ja vem com o IP verdadeiro do cliente injetado pelo CF; o nginx acrescenta o IP do CF em seguida. Considerar `ProxyFix` no Flask + `real_ip_header CF-Connecting-IP` se precisar de IP cliente puro nos logs do backend.
- **Rate limit de borda**: `limit_req_zone analytics_edge 10m rate=20r/s` aplicado no vhost da `api.*` (onde ingestao entra). Zone separada `cliente_auth 10m rate=10r/s` no `/api/cliente/auth/*` do apex (login/magic-link).
- **Client_max_body_size**: `1m` em ambos os vhosts publicos — payload de analytics e pequeno; limita abuso.
- **Admin**: rotas `/admin/*` do backend deveriam ficar atras de `allow` de IPs ou VPN alem do token. Exemplo comentado no `.conf` de referencia.

## Dashboard self-service do cliente — `/cliente/metricas/*`

O apex (`dsplayground.com.br`) expoe **3 blocos** alem do frontend padrao:

```nginx
# 1. API de auth do cliente — backend Flask
location /api/cliente/auth/ {
    limit_req zone=cliente_auth burst=20 nodelay;
    proxy_pass http://portifolio_backend;
    # ... headers padrao
}

# 2. Dashboard — Grafana com auth_request
location /cliente/metricas/ {
    auth_request /__cliente_auth_gate;
    auth_request_set $cliente_user  $upstream_http_x_webauth_user;
    auth_request_set $cliente_papel $upstream_http_x_webauth_papel;
    error_page 401 = @cliente_nao_autenticado;

    proxy_pass http://portifolio_grafana/;
    proxy_set_header X-WEBAUTH-USER  $cliente_user;
    proxy_set_header X-WEBAUTH-PAPEL $cliente_papel;
    # ... websocket headers + timeouts
}

# 3. Subrequest interna (nao acessivel externamente)
location = /__cliente_auth_gate {
    internal;
    proxy_pass http://portifolio_backend/api/cliente/auth/gate;
    proxy_pass_request_body off;
    # cookie segue automatico via proxy_pass_request_headers
}

location @cliente_nao_autenticado {
    return 302 /cliente/login;
}
```

Fluxo: browser pede `/cliente/metricas/foo` → nginx consulta `/__cliente_auth_gate` → Flask valida cookie `cliente_session` → retorna 200 + header `X-WEBAUTH-USER=<site_id>` → nginx propaga pro Grafana → Grafana auth.proxy auto-cria/loga user com username = site_id. Falha de cookie → 401 → 302 pra `/cliente/login`.

Detalhes do desenho em `ark/docs/dashboard-cliente.md`.
