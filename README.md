# @danpqdan/dsplayground-analytics-sdk

[![CI](https://github.com/danpqdan/dsplayground-analytics-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/danpqdan/dsplayground-analytics-sdk/actions/workflows/ci.yml) [![Publish](https://github.com/danpqdan/dsplayground-analytics-sdk/actions/workflows/publish.yml/badge.svg)](https://github.com/danpqdan/dsplayground-analytics-sdk/actions/workflows/publish.yml) [![status](https://img.shields.io/badge/status-alpha-yellow)](#) [![schema](https://img.shields.io/badge/schema-1.1-blue)](#)

SDK para coleta de eventos de navegacao, performance (Web Vitals) e eventos de negocio, com envio em tempo real via Socket.IO. A cada tick (default 5s) o SDK envia somente o que aconteceu desde a ultima emissao, entao queries agregadas no backend somam sem duplicar. Toda a coleta vive em `paginas[pageId][0].eventos` como uma lista unica `{ tipo, timestamp, dados }`.

Exemplos completos:

- [examples/standalone.html](./examples/standalone.html) — HTML estatico via `<script>` (UMD, sem bundler).
- [examples/vanilla.js](./examples/vanilla.js) — projeto JS/TS sem framework de UI mas com bundler (ESM `import`).
- [examples/react.tsx](./examples/react.tsx) — SPA React com `react-router-dom` + hook `useAnalyticsPagina`.

## Instalacao

### Via npm (recomendado)

```bash
npm install @danpqdan/dsplayground-analytics-sdk
```

```ts
import { iniciarAnalytics } from '@danpqdan/dsplayground-analytics-sdk';

iniciarAnalytics({
  websocketUrl: 'https://api.dsplayground.com.br',
  publishableKey: 'pk_production_xxxxx',  // gere em https://dsplayground.com.br/cliente/configuracoes/
  appId: 'meu-site',
  ambiente: 'production',
});
```

> **Pacote ainda nao publicado em npmjs.org publico** (planejado).
> Enquanto isso, instalar via GitHub Packages: configure `.npmrc` com
> `@danpqdan:registry=https://npm.pkg.github.com` e exporte um token GitHub
> com escopo `read:packages` em `NODE_AUTH_TOKEN`. Mais detalhes em
> [docs.github.com/packages](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-npm-registry).

### Standalone via `<script>` (HTML estatico, sem bundler)

Para Webflow, blogs WordPress, paginas de marketing — qualquer lugar onde
voce so consegue colar HTML+JS. Bundle IIFE com todas as deps inline
(~78 KB minificado, ~24 KB gzip).

**Opcao 1: jsDelivr CDN (recomendada)** — espelha GitHub Releases, com
edge cache global e versionamento imutavel:

```html
<script src="https://cdn.jsdelivr.net/gh/danpqdan/dsplayground-analytics-sdk@v0.3.2/dist/sdk.umd.js" defer></script>
```

**Opcao 2: GitHub Release direto** — funciona apos repo virar publico:

```html
<script src="https://github.com/danpqdan/dsplayground-analytics-sdk/releases/download/v0.3.2/sdk.umd.js" defer></script>
```

Ambos servem o mesmo arquivo. Use jsDelivr em prod (cache CDN) e release
direto pra testes.

```html
<script>
  window.addEventListener('load', () => {
    AnalyticsSDK.iniciarAnalytics({
      websocketUrl: 'https://api.dsplayground.com.br',
      publishableKey: 'pk_production_xxxxx',
      appId: 'meu-site',
      ambiente: 'production',
    });

    const heatmap = new AnalyticsSDK.HeatmapUtils(
      document.body,
      '[data-analytics-id], a, button',
      window.location.pathname,
    );
    heatmap.configurarColecaoTempoReal((d) =>
      AnalyticsSDK.WebSocketService.sendAnalyticsDataImmediate(d, false), 5000);
    heatmap.iniciarColecaoTempoReal();
    heatmap.iniciar();
  });
</script>
```

API completa exposta em `window.AnalyticsSDK`: `iniciarAnalytics`, `enviarEvento`, `HeatmapUtils`, `WebSocketService`, `FilaAnalytics` e os helpers de Storage.

## Embed em iframe / sub-frame

Casos de uso: dashboard embutido no painel de outro produto, widget num
super-app, demo do SDK numa pagina de marketing third-party. **A coleta
de eventos via Socket.IO funciona normalmente em iframe** — o handshake
WebSocket nao depende de cookies first-party. Mas alguns recursos
adjacentes tem comportamento especifico de third-party context:

### Content Security Policy (CSP)

Se a pagina-host tem CSP rigida, libere os endpoints abaixo:

```http
Content-Security-Policy:
  connect-src 'self' https://api.dsplayground.com.br wss://api.dsplayground.com.br;
  script-src 'self' https://cdn.jsdelivr.net;
```

- `connect-src` cobre o handshake HTTP do `polling` transport e o
  upgrade pro `wss://` (websocket). Sem `wss:` o SDK fica preso no
  long-polling — funciona, mas com 3-5x mais round-trips.
- `script-src https://cdn.jsdelivr.net` so e necessario se voce carrega
  o bundle UMD via jsDelivr. Em build com bundler (npm) o codigo vai
  pro proprio bundle e nao precisa de origem extra.
- O SDK **nao injeta** `<script>` ou `<style>` dinamico — entao
  `'unsafe-inline'` nao e necessario.

### Cookies em third-party context

Cookies `HttpOnly+Secure+SameSite=Strict` (como `cliente_session` do
backend dsplayground) **nao viajam quando a pagina-host esta num
dominio diferente do iframe**. Se sua aplicacao integrada usa o
dashboard do cliente embutido, o usuario sera redirecionado pra tela
de login. Workarounds:

- **Top-level navigation:** abra o dashboard em nova aba/janela
  (`<a target="_blank" rel="noopener">` ou `window.open`) — cookies
  same-site funcionam pra origem propria.
- **`SameSite=None; Secure`** no servidor: viabiliza cookies em
  third-party iframe, mas requer HTTPS em ambos os lados e deixa o
  cookie alvo de CSRF se nao houver `SameSite=Strict` na auth de
  formulario. **Nao trocamos** `cliente_session` pra `None` por essa
  razao.
- **Iframe na mesma eTLD+1:** se o host e o dashboard compartilham
  eTLD+1 (`app.dsplayground.com.br` dentro de
  `dashboard.dsplayground.com.br`), o cookie funciona porque o
  `Domain=dsplayground.com.br` cobre ambos. Esse e o padrao oficial.

### Coleta em iframe

`HeatmapUtils` so observa o documento que recebe como `root` (default:
`document.body`). Eventos do **iframe pai** nao sao capturados — cada
frame precisa do proprio SDK rodando, com `appId`/`pageId` que reflitam
o contexto. Isso e proposital: cross-frame DOM access requer
same-origin e quebraria sob CSP.

## Build local

```bash
npm install
npm run build   # gera dist/{index.js, index.cjs, index.d.ts, sdk.umd.js} (minificado via esbuild)
npm run test    # 89 unit tests (Vitest + jsdom, 18 arquivos)
npm run smoke   # confere que dist/ tem ESM + CJS + .d.ts + UMD validos
npm run lint    # tsc --noEmit
```

Sub-builds disponiveis individualmente: `npm run build:lib` (ESM+CJS+.d.ts) e `npm run build:umd` (IIFE standalone).

Externals preservados (`react`, `react-dom`, `socket.io-client`, `uuid`, `web-vitals`) — quem consome resolve essas dependencias no proprio bundler.

## Inicializacao

Chame `iniciarAnalytics` uma vez no boot da aplicacao, antes de qualquer outro uso do SDK. Qualquer chamada anterior a isso vira no-op.

```ts
import { iniciarAnalytics } from '@danpqdan/dsplayground-analytics-sdk';

iniciarAnalytics({
  websocketUrl: 'http://localhost:5000',
  publishableKey: 'pk_development_xxxxx',
  appId: 'meu-site',
  ambiente: 'development',
  debug: true,
  intervaloEnvioMs: 5000,
  coletarPerformance: true,
  taxaAmostragemMouseMove: 5,
});
```

`websocketUrl`, `appId` e `ambiente` sao obrigatorios. Os demais tem default sensato: 5s de intervalo, Web Vitals ligados e amostragem de mouse em 5 pontos/segundo.

## Coleta automatica

A coleta de cada pagina precisa de um `HeatmapUtils` instanciado no ciclo de vida dela. O padrao React fica assim:

```tsx
import { useEffect } from 'react';
import { HeatmapUtils, WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';

export function useAnalyticsPagina(pageId: string, hoverSelector?: string) {
  useEffect(() => {
    const heatmap = new HeatmapUtils(document.body, hoverSelector ?? null, pageId);

    heatmap.configurarColecaoTempoReal((dados) => {
      WebSocketService.sendAnalyticsDataImmediate(dados, false);
    }, 5000);
    heatmap.iniciarColecaoTempoReal();
    heatmap.iniciar();

    return () => heatmap.parar();
  }, [pageId, hoverSelector]);
}
```

`heatmap.iniciar()` empilha um `page_view` e liga os handlers DOM. `heatmap.parar()` empilha um `page_exit` com `duracao_ms` e `motivo`, drena o residuo da janela atual e solta os listeners — nao e preciso enviar manualmente no unmount.

Para consumidores fora do React, o exemplo em [examples/vanilla.js](./examples/vanilla.js) mostra a mesma sequencia no `DOMContentLoaded` e `beforeunload`, incluindo troca de pagina em SPA sem router.

## Eventos de negocio

Use `enviarEvento` em pontos-chave do funil. O evento entra na pagina ativa como tipo `custom`, junto com os demais:

```ts
import { enviarEvento } from '@danpqdan/dsplayground-analytics-sdk';

enviarEvento('checkout_iniciado', {
  plano: 'pro',
  preco: 99.9,
  recorrente: true,
});
```

Apenas valores primitivos (string, number, boolean, null) sao aceitos. Objetos, arrays e funcoes sao descartados silenciosamente para evitar vazamento acidental de dados estruturados. O nome tem limite de 64 caracteres, strings de ate 512 caracteres, ate 32 chaves por evento. Retorna `false` se o nome/propriedades sao invalidos.

> **Pre-iniciar buffer (v0.3.1+):** se nao ha `HeatmapUtils` ativo no momento do
> `enviarEvento`, o evento e enfileirado em buffer global (cap 100) e drenado
> pra primeira pagina que chamar `iniciar()`. Mesmo comportamento se aplica aos
> callbacks de Web Vitals. Antes de v0.3.1 esses eventos eram silenciosamente
> descartados — bug que afetava apps registrando analytics no module-load
> (ex.: `App.jsx` chamando `iniciarAnalytics` antes de qualquer route mount).
> A partir de v0.3.1, `enviarEvento` retorna `true` quando enfileira sem
> pagina ativa.

## Marcar elementos importantes

O `elemento_id` de cada click, touch, hover e exposicao e resolvido nesta ordem: `data-analytics-id`, `id`, `aria-label`, primeira classe, `tagName`. Como `data-analytics-id` e controlado explicitamente pelo consumidor, ele nao quebra quando o CSS ou a estrutura HTML mudam. Prefira marcar elementos sensiveis ao analytics com esse atributo:

```html
<button data-analytics-id="cta-comprar-pro">Comprar agora</button>
```

## Web Vitals

Quando `coletarPerformance` esta ligado (default), o SDK registra listeners de LCP, CLS e INP atraves da lib [`web-vitals`](https://github.com/GoogleChrome/web-vitals). As metricas viram eventos `web_vital` no buffer da pagina ativa no momento em que ficam disponiveis (LCP apos a primeira pintura, CLS no lifecycle, INP na primeira interacao). No backend, Web Vitals sao persistidos em um measurement separado (`web_vitals`) para nao poluir as contagens comportamentais.

Desligue passando `coletarPerformance: false` no `iniciarAnalytics`.

## Planos e quotas

A partir do modo comercial (proposto, ver `ark/docs/dashboard-cliente.md` sec. 18), o backend enforce limites por plano em **3 dimensoes**: eventos/mes, retencao, cardinalidade max de tags. O SDK **nao** tem conhecimento direto do plano — ele simplesmente envia, o backend aceita ou rejeita.

| Plano | Eventos/mes | Retencao | Cardinalidade max | Backup |
|---|---|---|---|---|
| free | 10k | 7 dias | 1k tag values | nao |
| pequeno | 100k | 30 dias | 5k | semanal |
| medio | 1M | 90 dias | 50k | diario |
| grande | 10M | 365 dias | 500k | diario + arquivo 12m |

Quando a quota estoura, o backend retorna `analytics_error code=QUOTA_EXCEDIDA` no proximo batch. O SDK ja trata: pausa envios e tenta de novo apos a janela (definida no campo `retry_after_ms` da resposta). Eventos pendentes na fila offline aguardam.

## Tags e contrato com o backend

O payload base (`paginas[pageId][0]`) carrega **3 tags ja obrigatorias** que o SDK setа automaticamente:

| Tag | Origem | Obrigatorio |
|---|---|---|
| `app_id` | `iniciarAnalytics({ appId })` | **Sim** — backend rejeita conexao sem |
| `ambiente` | `iniciarAnalytics({ ambiente })` | **Sim** — `development\|test\|staging\|production` |
| `page_type` | id passado em `new HeatmapUtils(_, _, pageId)` | **Sim** — sem isso o evento e descartado |

Tags **derivadas server-side** (nao precisa enviar):

- `device_type` (mobile/tablet/desktop, derivado do User-Agent)
- `pais` (derivado do IP via GeoIP, opt-in do operador)
- `referrer_dominio` (so o dominio, nao path)

Tags **proibidas** — campos com cardinalidade alta que seriam tags candidatas mas detonam o InfluxDB. Se o consumidor passar via `enviarEvento`, viram **fields**, nao tags:

- `user_id`, `session_id`, `email`, `request_id`, `url_completa`

> Em `enviarEvento(nome, propriedades)`, todas as propriedades sao gravadas como **fields**, nao tags. Isso e proposital: fields aceitam alta cardinalidade sem custo. Use props pra correlacionar em queries (`where r._field == "plano"`), nao pra agregar dimensoes (que seria caso de tag).

## Codigos de erro do backend

O servidor responde via Socket.IO com `analytics_error { status, code, message }`. Tabela de codigos que o SDK pode receber:

| `code` | HTTP equiv | Quando | O que o SDK faz | Acao do consumidor |
|---|---|---|---|---|
| `INVALID_SESSION` | 401 | Cookie expirou ou hijack detectado | Disconnect + reconnect | Nada — automatico |
| `RATE_LIMIT` | 429 | Limite por sessao (default 10k batches) | Pausa envio, retry com backoff | Verificar `SESSION_REQUEST_LIMIT` no backend |
| `RATE_LIMIT_EXCEDIDO` | 429 | Magic-link burst (auth, nao analytics) | n/a (so auth) | n/a |
| `QUOTA_EXCEDIDA` | 429 | Plano estourou eventos/dia ou /mes | Pausa ate `retry_after_ms` | **Upgrade do plano** |
| `EMPTY_PAYLOAD` | 400 | Batch chegou sem dados uteis | Sinaliza no log | Verificar lifecycle do `HeatmapUtils` |
| `TAG_REJEITADA` (futuro) | 400 | Tag fora da whitelist ou faltando obrigatoria | Loga + descarta evento | **Bug no integrador** — corrigir o `appId`/`pageId` |
| `CARDINALIDADE_EXCEDIDA` (futuro) | 429 | Bucket atingiu limite de tag values | Loga | **Bug** — provavelmente passou `user_id` como tag custom |
| `INTERNAL_ERROR` | 500 | Falha do backend | Retry com backoff | Suporte |

`SCHEMA_VERSION_MISMATCH` retornado em `connect`: SDK e backend desalinhados (versao SDK < `min_client_schema`). SDK precisa ser atualizado.

## Privacidade

Nada de `innerText`, `textContent` ou `value` de input sai do dispositivo. A URL coletada e apenas o `pathname` — querystring fica de fora. O unico fingerprint e `user_agent` e um `device_type` derivado (`mobile | tablet | desktop`). O `mouse_move` tem amostragem agressiva de 5 pontos/segundo por default, justamente para limitar volume e granularidade. Em `enviarEvento`, objetos e arrays sao descartados para reduzir risco de PII estruturado. Qualquer dado fora dessa linha exige opt-in explicito do consumidor.

## LGPD e uso por terceiros

O SDK e uma ferramenta tecnica: ele nao obtem consentimento, nao mantem um identificador de pessoa natural e nao julga o que pode ou nao ser coletado. A conformidade com a LGPD emerge da forma como o consumidor configura, liga e integra o SDK na aplicacao. Esta secao separa o que o SDK ja entrega pronto do que a aplicacao integradora precisa fazer.

### O que o SDK garante por padrao

A identificacao de sessao (`id_registro`) e um UUID v4 gerado no navegador e nao carrega nenhum dado pessoal. Conteudo textual da pagina, valores de input e querystring ficam sempre fora do payload. Eventos customizados sao filtrados para so aceitar primitivos, o que bloqueia o caminho mais comum de vazamento nao intencional de PII (objetos grandes serializados sem auditoria). Web Vitals, por natureza da lib, sao medidas tecnicas sem vinculo com identidade. O SDK nao usa cookies.

**Armazenamento local.** A fila offline grava eventos ainda nao confirmados em `IndexedDB` (com fallback para `localStorage`) para sobreviver a quedas de rede e recarregamentos de pagina. Esse armazenamento contem apenas os proprios payloads de analytics — mesmas regras de privacidade acima se aplicam. Para a LGPD, qualquer armazenamento local alem do estritamente necessario exige mencao no banner de consentimento do integrador. Quando o titular revogar consentimento, chame `WebSocketService.limparFilaOffline()` para purgar tudo.

### O que o integrador precisa fazer

**Consentimento.** A LGPD exige base legal para tratamento. Para analytics de comportamento em geral vale consentimento explicito; em casos especificos pode se apoiar em legitimo interesse com transparencia e opt-out. Em qualquer cenario, o padrao recomendado e nao chamar `iniciarAnalytics` antes da decisao do titular:

```ts
if (consentimento.aceitouAnalytics) {
  iniciarAnalytics({ /* ... */ });
}
```

Se o usuario revogar o consentimento em tempo de execucao, chame `WebSocketService.disconnect()`, pare de instanciar novos `HeatmapUtils` e, crucialmente, `await WebSocketService.limparFilaOffline()` para apagar o que ja foi persistido localmente mas ainda nao chegou ao backend. Eventos ja entregues ao backend antes da revogacao sao responsabilidade do operador (ver "Direitos dos titulares").

**Papeis.** Via de regra, o dono da aplicacao que integra o SDK e o **controlador** (decide quais dados coletar e para que). O operador de backend (quem roda a API Socket.IO + InfluxDB) e o **operador** na definicao da LGPD. Se voce roda o proprio backend, cumula os dois papeis e assume ambos os deveres. Registre esse arranjo no seu mapa de tratamento de dados.

**Politica de privacidade.** Declare na politica publica da aplicacao: que eventos sao coletados, por que, quanto tempo ficam retidos, se saem do Brasil, quem e o operador e como o titular exerce os direitos dele. O [catalogo de eventos](../../../docs/eventos-analytics-catalogo.md) da a lista completa para copiar.

**Eventos customizados.** `enviarEvento` nao e filtro de dado sensivel — e filtro de estrutura. Voce ainda pode passar um CPF dentro de uma string e ele passa. Trate `enviarEvento` como uma superficie que voce controla: padronize nomes, revise o que cada ponto de chamada envia e, quando precisar referenciar um titular, prefira identificadores pseudonimizados (hash com salt) em vez do dado bruto.

**Retencao.** Configure politica de retencao no bucket do InfluxDB com o prazo compativel com a finalidade declarada. Sem retencao configurada o operador fica exposto a armazenar dado alem do necessario.

**Direitos dos titulares.** A LGPD obriga responder a pedidos de acesso, correcao, anonimizacao, portabilidade e exclusao. Como as metricas sao tageadas por `session_id` (no backend) e o SDK propaga `id_registro` no envelope, o caminho e:

1. mapear no seu sistema a relacao entre usuario identificado e os `id_registro`/`session_id` que ele gerou;
2. expor um endpoint administrativo que consulta ou apaga pontos no InfluxDB filtrando por essas tags;
3. documentar o SLA desse endpoint na politica.

**Crianças e dados sensiveis.** Se a aplicacao e acessada por criancas ou trata dados sensiveis (saude, biometria, etc.), o SDK nao e suficiente sozinho — e preciso base legal especifica e, para criancas, consentimento parental. Nao use `enviarEvento` para transportar esses dados.

### Checklist de integracao

Antes de subir o SDK em producao, confirme:

- [ ] Consentimento obtido (ou base legal documentada) antes de `iniciarAnalytics`.
- [ ] Politica de privacidade atualizada com eventos, finalidade, retencao e operador.
- [ ] Banner de cookies/preferencias menciona o armazenamento local da fila offline (`IndexedDB`/`localStorage`).
- [ ] Revisao de todos os pontos de `enviarEvento` — nenhum passa PII em claro.
- [ ] Retencao configurada no bucket InfluxDB.
- [ ] Endpoint admin de consulta/exclusao por `session_id` implementado e testado.
- [ ] Revogar consentimento executa `WebSocketService.disconnect()` + `WebSocketService.limparFilaOffline()`.

## Catalogo de eventos

O detalhamento de campos, regras de emissao e motivacao por tipo fica em [docs/eventos-analytics-catalogo.md](./docs/eventos-analytics-catalogo.md).

Os tipos emitidos sao:

| tipo | quando | origem |
|---|---|---|
| `page_view` | em `heatmap.iniciar()` | automatico |
| `page_exit` | em `heatmap.parar()` com `duracao_ms` e `motivo` | automatico |
| `click` / `touch` | clique/toque DOM | automatico |
| `scroll_depth` | ao atingir os marcos 25/50/75/100 | automatico |
| `mouse_move` | movimentos, amostrados | automatico |
| `hover` | no `mouseleave` de elementos do `hoverSelector` | automatico |
| `element_exposure` | ao sair do viewport (IntersectionObserver) | automatico |
| `web_vital` | quando web-vitals entrega a metrica | automatico (se `coletarPerformance=true`) |
| `custom` | via `enviarEvento` | manual |

## API

```ts
iniciarAnalytics(config: AnalyticsConfig): void
enviarEvento(nome: string, propriedades?: Record<string, unknown>): boolean

class HeatmapUtils {
  constructor(root?: HTMLElement, hoverSelector?: string | null, paginaTipo?: string);
  iniciar(): void;
  parar(motivo?: 'navegacao' | 'unmount' | 'aba_fechada'): void;
  configurarColecaoTempoReal(
    cb: (dados: HeatmapDados) => void,
    intervaloMs?: number,
    taxaAmostragemMouseMove?: number,
  ): void;
  iniciarColecaoTempoReal(): void;
  emitirDeltaAgora(): void;
  getDados(): HeatmapDados;
  getTempoPermanciaSegundos(): number;

  static getDadosGlobais(): HeatmapDados;
  static resetarRegistro(): void;
}

const WebSocketService: {
  connect(): Promise<boolean>;
  disconnect(): void;
  sendAnalyticsData(d: HeatmapDados): Promise<boolean>;
  sendAnalyticsDataImmediate(d: HeatmapDados, prioritario?: boolean): Promise<boolean>;
  getConnectionStatus(): { isConnected: boolean; socketId: string | null; attempts: number; pendingData: number };
  setRealtimeInterval(ms: number): void;
  limparFilaOffline(): Promise<void>;
  tamanhoFilaOffline(): Promise<number>;
};
```

Tipos exportados: `AnalyticsConfig`, `Ambiente`, `HeatmapDados`, `PaginaDados`, `EventoNormalizado`, `TipoEvento`, `MarcoScroll`, `MotivoSaida`, `NomeWebVital`, `RatingWebVital`, `MapaPaginasDados`.

## Contribuindo / desenvolvimento

Pre-commit hooks rodam automaticamente apos `npm install` (via `husky`):

| Camada | O que checa | Como pular |
|---|---|---|
| `lint-staged` | `tsc --noEmit` em arquivos staged | corrige erros TS |
| `gitleaks protect` | secrets em arquivos staged (regras default + custom em `.gitleaks.toml`) | `git commit --no-verify` se ja conferiu |
| `npm audit --audit-level=high` | CVE high+ em deps de prod | `npm audit fix` ou `--no-verify` |

`gitleaks` precisa estar instalado localmente (`brew install gitleaks` /
`scoop install gitleaks` / [releases](https://github.com/gitleaks/gitleaks#installing)).
Sem ele, o pre-commit avisa e segue — **CI ainda roda gitleaks no PR**, entao
nada vai pra `main` sem passar.

Scripts uteis:

```bash
npm run lint           # tsc --noEmit
npm test               # vitest run
npm run audit:high     # mesma checagem do pre-commit
npm run secrets:scan   # gitleaks full-history (mais pesado)
npm run build          # ESM + CJS + UMD
npm run smoke          # validar artefatos em dist/
```
