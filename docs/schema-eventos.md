# Schema formal de eventos

Especificacao do contrato de wire entre SDK e backend. Todo evento que sai
do SDK passa por um normalizador (em `src/normalizadores/`) e tem a forma
canonica abaixo. Este documento e a fonte de verdade para validar payloads
em CI, escrever fixtures de teste e implementar parsers em outras
linguagens (ex.: backend Python).

Para a motivacao de cada evento (por que coletar, o que ele responde),
ver [eventos-analytics-catalogo.md](./eventos-analytics-catalogo.md).
Este arquivo cobre apenas o **shape**.

## Envelope

Todo evento normalizado tem exatamente tres campos no nivel raiz:

```json
{
  "tipo": "<TipoEvento>",
  "timestamp": 0,
  "dados": { /* payload especifico do tipo */ }
}
```

```typescript
interface EventoNormalizado {
  tipo: TipoEvento;
  timestamp: number;            // ms desde epoch (Date.now())
  dados: Record<string, unknown>;
}

type TipoEvento =
  | 'page_view'
  | 'page_exit'
  | 'click'
  | 'touch'
  | 'scroll_depth'
  | 'mouse_move'
  | 'hover'
  | 'element_exposure'
  | 'web_vital'
  | 'custom';
```

JSON Schema do envelope:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://dsplayground.com.br/schemas/sdk/evento-normalizado.json",
  "type": "object",
  "required": ["tipo", "timestamp", "dados"],
  "additionalProperties": false,
  "properties": {
    "tipo": {
      "type": "string",
      "enum": [
        "page_view", "page_exit", "click", "touch", "scroll_depth",
        "mouse_move", "hover", "element_exposure", "web_vital", "custom"
      ]
    },
    "timestamp": {
      "type": "integer",
      "minimum": 0,
      "description": "ms desde epoch (Unix time * 1000)"
    },
    "dados": { "type": "object" }
  }
}
```

## Tipos por evento

### `page_view`

```json
{
  "tipo": "page_view",
  "timestamp": 1748793600000,
  "dados": {
    "page_id": "/checkout",
    "path": "/checkout",
    "title": "Checkout - Loja"
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `page_id` | string | sim | identificador logico (ver `new HeatmapUtils(_, _, pageId)`) |
| `path` | string | sim | `window.location.pathname` (sem querystring) |
| `title` | string \| null | nao | `document.title` quando disponivel |

```json
{ "type": "object", "required": ["page_id", "path"], "properties": {
  "page_id": { "type": "string", "minLength": 1 },
  "path": { "type": "string", "minLength": 1 },
  "title": { "type": ["string", "null"] }
}}
```

### `page_exit`

```json
{
  "tipo": "page_exit",
  "timestamp": 1748793612345,
  "dados": {
    "page_id": "/checkout",
    "duracao_ms": 12345,
    "motivo": "navegacao"
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `page_id` | string | sim | igual ao `page_view` correspondente |
| `duracao_ms` | integer ≥ 0 | sim | tempo entre `iniciar()` e `parar()` |
| `motivo` | enum | sim | `navegacao` \| `unmount` \| `aba_fechada` |

### `click`

```json
{
  "tipo": "click",
  "timestamp": 1748793605000,
  "dados": {
    "x": 412,
    "y": 256,
    "elemento_id": "cta-comprar",
    "elemento_tipo": "button"
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `x` | number | sim | `event.pageX` (coordenada absoluta) |
| `y` | number | sim | `event.pageY` |
| `elemento_id` | string | sim | resolvido por `obterElementoId` (ordem: `data-analytics-id`, `id`, `aria-label`, primeira classe, `tagName`) |
| `elemento_tipo` | string | sim | `tagName` em minusculo |

### `touch`

Mesma forma de `click`. Diferenca: `elemento_id` resolvido via
`document.elementFromPoint(x, y)` em vez de `event.target` (touch events
nao expoem `target` confiavel em todos os browsers).

### `scroll_depth`

```json
{
  "tipo": "scroll_depth",
  "timestamp": 1748793607000,
  "dados": {
    "marco": 50,
    "max_percent": 53
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `marco` | enum | sim | `25` \| `50` \| `75` \| `100` |
| `max_percent` | integer 0-100 | sim | percent maximo ja atingido (`>= marco`) |

Emitido **uma unica vez por marco** por instancia de `HeatmapUtils`. Scroll
para tras nao re-emite.

### `mouse_move`

```json
{
  "tipo": "mouse_move",
  "timestamp": 1748793608100,
  "dados": { "x": 412, "y": 256 }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `x` | number | sim | `event.pageX` |
| `y` | number | sim | `event.pageY` |

Amostragem: `taxaAmostragemMouseMove` pontos/segundo (default 5 → 1 a cada
200ms). Eventos DOM intermediarios entre amostras sao descartados.

### `hover`

```json
{
  "tipo": "hover",
  "timestamp": 1748793609500,
  "dados": {
    "elemento_id": "card-plano-pro",
    "elemento_tipo": "div",
    "duracao_ms": 1250
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `elemento_id` | string | sim | |
| `elemento_tipo` | string | sim | |
| `duracao_ms` | integer ≥ 0 | sim | tempo entre `mouseenter` e `mouseleave` |

So elementos cobertos pelo `hoverSelector` (passado em
`new HeatmapUtils(_, hoverSelector, _)`) emitem.

### `element_exposure`

```json
{
  "tipo": "element_exposure",
  "timestamp": 1748793611000,
  "dados": {
    "elemento_id": "secao-precos",
    "duracao_ms": 4200,
    "percent_visivel_max": 87
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `elemento_id` | string | sim | |
| `duracao_ms` | integer ≥ 0 | sim | tempo total que o elemento esteve visivel nesta janela |
| `percent_visivel_max` | integer 0-100 | nao | maior `intersectionRatio * 100` observado |

Emitido no `IntersectionObserver` callback quando o elemento sai do
viewport. Em `parar()`, elementos ainda visiveis emitem com a duracao
ate aquele momento.

### `web_vital`

```json
{
  "tipo": "web_vital",
  "timestamp": 1748793604000,
  "dados": {
    "nome": "LCP",
    "valor": 1850.4,
    "rating": "good",
    "id": "v3-1748793600000-1234567890"
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `nome` | enum | sim | `LCP` \| `CLS` \| `INP` |
| `valor` | number | sim | valor bruto entregue por `web-vitals` |
| `rating` | enum | nao | `good` \| `needs-improvement` \| `poor` |
| `id` | string | nao | id interno da lib `web-vitals` (util pra dedupe) |

CLS e adimensional; LCP e INP sao milissegundos. Persistido em measurement
separado (`web_vitals`) no InfluxDB.

### `custom`

```json
{
  "tipo": "custom",
  "timestamp": 1748793613000,
  "dados": {
    "nome": "checkout_iniciado",
    "propriedades": {
      "plano": "pro",
      "preco": 99.9,
      "recorrente": true
    }
  }
}
```

| campo | tipo | obrigatorio | descricao |
|---|---|---|---|
| `nome` | string | sim | identificador, 1-64 chars, `[a-zA-Z0-9_]` recomendado |
| `propriedades` | object | nao | chaves: 1-64 chars, ate 32 entradas; valores: primitivos (string ate 512 chars, number, boolean, null) |

**Filtros aplicados em `enviarEvento`:**

- Nome > 64 chars → evento descartado, retorna `false`.
- Mais de 32 chaves → entradas alem da 32a ignoradas.
- Valor nao primitivo (objeto, array, funcao, undefined) → entrada
  descartada silenciosamente. Nao retorna erro.
- String > 512 chars → truncada em 512.

## Buffer pre-iniciar (v0.3.1+)

Eventos disparados via `enviarEvento` **antes do primeiro
`heatmap.iniciar()`** ficam num buffer global (cap 100, FIFO descartando
**os mais novos** ao estourar) e sao drenados pra primeira pagina ativa.
Mesmo comportamento aplica-se aos callbacks de Web Vitals registrados em
`iniciarWebVitals()` antes de qualquer HeatmapUtils estar ativo.

O buffer **nao** e persistido — recarregar a pagina perde o que estiver
nele. Para garantir entrega de eventos de boot, chame `iniciarAnalytics`
+ `enviarEvento('app_carregado', ...)` no module-load (ver
`examples/react.tsx`).

## Envelope completo (multiplos eventos)

O SDK envia em batches (`HeatmapDados`) via `WebSocketService`:

```json
{
  "id_registro": "9c0a3f12-...",
  "user_agent": "Mozilla/5.0 ...",
  "device_type": "desktop",
  "paginas": {
    "/checkout": [
      {
        "page_type": "/checkout",
        "app_id": "minha-spa",
        "ambiente": "production",
        "eventos": [
          { "tipo": "page_view", "timestamp": 1748793600000, "dados": { ... } },
          { "tipo": "click", "timestamp": 1748793605000, "dados": { ... } },
          { "tipo": "scroll_depth", "timestamp": 1748793607000, "dados": { ... } }
        ]
      }
    ]
  }
}
```

A cada tick (default 5s) o SDK envia **somente eventos novos** desde a
ultima emissao. Backend agrega por tipo em `TemporalMetric` — nao precisa
deduplicar do lado do servidor.

## Versionamento

`SDK_SCHEMA_VERSION = '1.1'` (constante exportada). Backend rejeita
conexoes com schema fora do range suportado (`min_client_schema` no handshake)
retornando `426 Upgrade Required`.

Mudancas que bumpam schema major:

- Remocao ou renomeacao de campo obrigatorio.
- Mudanca de tipo de campo (ex.: `duracao_ms` vira string).
- Novo tipo de evento que o backend ainda nao sabe persistir.

Mudancas que bumpam schema minor:

- Campo opcional novo num evento existente.
- Novo enum-value em campo enum (com fallback documentado).
- Endurecimento de filtros server-side que nao quebra clientes ja conformes.
