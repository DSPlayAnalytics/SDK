# DNS — dsplayground.com.br via Cloudflare

O dominio esta registrado no **Registro.br** e delegado para nameservers Cloudflare:

```
bonnie.ns.cloudflare.com
jeremy.ns.cloudflare.com
```

Toda edicao de DNS acontece no **painel do Cloudflare**, nao no Registro.br. No Registro.br a unica coisa relevante sao os NS acima — nao mexer.

## Pre-requisito: conta Cloudflare com o dominio adicionado

Se ainda nao esta adicionado no Cloudflare:

1. Login em https://dash.cloudflare.com.
2. **Add a site** → digite `dsplayground.com.br` → plano Free.
3. Cloudflare varre os DNS atuais — como a zona pode estar vazia, ignore.
4. Cloudflare mostra os NS que voce precisa apontar no Registro.br (devem bater com `bonnie` e `jeremy` acima — se bater, tudo certo).

No dashboard do Cloudflare, o painel inicial deve mostrar a zona como **"Active"**. Se aparecer "Pending Nameserver Update", o Registro.br ainda nao propagou os NS — aguardar (tipicamente < 24h).

## Registros A necessarios

Criar em **Websites → dsplayground.com.br → DNS → Records → Add record**:

| Type | Name | IPv4 | Proxy status | TTL |
|---|---|---|---|---|
| A | `@` (ou `dsplayground.com.br`) | `129.121.55.29` | **DNS only** (nuvem cinza) | Auto |
| A | `www` | `129.121.55.29` | **DNS only** (nuvem cinza) | Auto |
| A | `portifolio` | `129.121.55.29` | **Proxied** (nuvem laranja) | Auto |
| A | `app` | `129.121.55.29` | **Proxied** (nuvem laranja) | Auto |
| A | `api` | `129.121.55.29` | **Proxied** (nuvem laranja) | Auto |
| A | `grafana` | `129.121.55.29` | **Proxied** (nuvem laranja) | Auto |
| A | `influx` | `129.121.55.29` | **Proxied** (nuvem laranja) | Auto |

> **portifolio.dsplayground.com.br** e o frontend React 3D (portfolio pessoal) servido pelo
> container `portifolio-frontend` em `127.0.0.1:3000`. Nao e a landing comercial — essa vive
> no CF Pages (`dsplayground.com.br` apex). Subdominios `app`, `api`, `grafana`, `influx`
> devem sempre ser **Proxied** (laranja) para que o CF Origin Cert wildcard (ate 2041)
> seja valido no TLS. Nunca cinza em producao.

### Por que "DNS only" inicialmente

O certbot usa **HTTP-01 challenge**: o ACME do Let's Encrypt precisa bater direto no IP `129.121.55.29:80` e ler um arquivo escrito pelo nginx. Com o proxy Cloudflare ligado (nuvem laranja), o trafego entra na edge da Cloudflare — e **o certbot falha** porque o challenge nao chega no servidor.

**Sequencia correta**:

1. Criar os A records com nuvem **cinza** (DNS only).
2. Aguardar propagacao (`dig +short dsplayground.com.br @1.1.1.1` → `129.121.55.29`).
3. Rodar o playbook ansible — certbot emite o cert com sucesso.
4. **So entao**, opcional: ligar nuvem laranja no Cloudflare para ganhar CDN/WAF. Neste caso, no painel Cloudflare **SSL/TLS** selecione modo **Full (strict)** — usa o cert Let's Encrypt do servidor.

Se precisar emitir o cert com o proxy ja ligado, o caminho e DNS-01 challenge via Cloudflare API — fora do escopo atual. Prefira desligar o proxy para o primeiro emission, religar depois.

## Validar a propagacao

```bash
# Do host local (funciona em qualquer DNS resolver)
dig +short dsplayground.com.br @1.1.1.1
dig +short www.dsplayground.com.br @1.1.1.1
# esperado: 129.121.55.29 em ambos

# Conferir por varios resolvers (elimina cache local)
for r in 1.1.1.1 8.8.8.8 9.9.9.9; do
  echo "-- $r"
  dig +short dsplayground.com.br @$r
done
```

Se algum dos resolvers devolve vazio mas outros ja devolvem o IP, e propagacao em andamento — aguardar 5-15 min.

## Registros opcionais (para mais tarde)

| Type | Name | Content | Uso |
|---|---|---|---|
| CAA | `@` | `0 issue "letsencrypt.org"` | restringe emissao de cert a Let's Encrypt |
| MX | `@` | (depende de provedor de e-mail) | se for receber email@dsplayground.com.br |
| TXT | `@` | `v=spf1 -all` | evita spoof de e-mail se nao usar email proprio |

CAA nao e obrigatorio mas e boa pratica — impede que outra CA emita cert para o dominio caso a conta de alguem for comprometida.

## Troubleshooting

### `dig` retorna vazio

```bash
dig dsplayground.com.br NS @1.1.1.1
```
- Se retorna `bonnie.ns.cloudflare.com` e `jeremy.ns.cloudflare.com`, os NS estao OK — problema e no registro A.
- Se retorna outros NS ou vazio, o Registro.br ainda nao propagou — aguardar ou revisar no painel.

### `dig` retorna IP errado

Conferir no Cloudflare se o registro A esta mesmo apontando para `129.121.55.29`. As vezes um registro antigo (do parking do dominio) sobrevive — deletar.

### Certbot falha mesmo com DNS OK

Conferir:
1. Firewall do servidor tem porta 80 aberta (`firewall-cmd --list-all`).
2. Nginx esta respondendo em HTTP (`curl -I http://dsplayground.com.br/`).
3. Nuvem do Cloudflare **cinza** (DNS only) no momento da emissao.
