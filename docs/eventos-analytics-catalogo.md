# Catalogo de Eventos de Analytics

Este catalogo define o contrato publico dos eventos emitidos pelo SDK. Cada emissao via Socket.IO traz um conjunto de eventos normalizados em `paginas[pageId][0].eventos`. Sao emitidos apenas eventos ocorridos na janela atual (delta por tick).

Todo evento tem a forma:

```ts
{ tipo: string, timestamp: number, dados: Record<string, unknown> }
```

## Regras gerais

- Todo evento passa por um normalizador — nada de payload bruto.
- O campo `elemento_id` e resolvido na ordem `data-analytics-id` > `id` > `aria-label` > primeira classe > `tagName`. Preferir `data-analytics-id` em elementos importantes evita que o id quebre com refactor de CSS.
- Nunca sao coletados sem opt-in explicito: `innerText`/`textContent`, `value` de inputs, querystring da URL (so `pathname`), fingerprint alem de `user_agent` e `device_type` derivado.
- `mouse_move` tem amostragem (default 5 pontos/segundo) configuravel por `iniciarAnalytics({ taxaAmostragemMouseMove })`.

## Eventos

### `page_view`

Emitido em `heatmap.iniciar()`.

| campo | tipo | descricao |
|---|---|---|
| `page_id` | string | identificador logico da pagina (rota) |
| `path` | string | caminho URL sem querystring |
| `title` | string? | titulo da pagina quando disponivel |

Por que coletar: contagem de visualizacoes, funnel de paginas, atribuicao de demais eventos a uma pagina.

### `page_exit`

Emitido em `heatmap.parar()`.

| campo | tipo | descricao |
|---|---|---|
| `page_id` | string | igual ao `page_view` |
| `duracao_ms` | number | tempo desde `iniciar()` ate `parar()` |
| `motivo` | `'navegacao' \| 'unmount' \| 'aba_fechada'` | fonte da saida |

Por que coletar: bounce rate, tempo medio de permanencia, diferenciar saida natural (`navegacao`) de desmontagem de componente (`unmount`) ou fechamento de aba (`aba_fechada`).

### `click`

| campo | tipo | descricao |
|---|---|---|
| `x`, `y` | number | coordenadas absolutas da pagina |
| `elemento_id` | string | resolvido pelo seletor padrao |
| `elemento_tipo` | string | `tagName` em minusculo |

Por que coletar: heatmap de interacao, identificacao de CTAs efetivos.

### `touch`

Equivalente mobile de `click`. Mesma forma de `click` mais `elemento_id` resolvido via `document.elementFromPoint`.

Por que coletar: heatmap de interacao em dispositivos touch.

### `scroll_depth`

| campo | tipo | descricao |
|---|---|---|
| `marco` | `25 \| 50 \| 75 \| 100` | marco atingido |
| `max_percent` | number | percent maximo ja alcancado no scroll |

Emitido uma unica vez por marco atingido, nao a cada evento DOM de scroll.

Por que coletar: engajamento de leitura, decisao sobre reestruturar conteudo abaixo da dobra.

### `mouse_move`

| campo | tipo | descricao |
|---|---|---|
| `x`, `y` | number | coordenadas absolutas |

Amostragem default: 5 pontos/segundo (1 a cada 200ms).

Por que coletar: heatmap de movimento e deteccao de areas mortas. Caro em volume; use `taxaAmostragemMouseMove` para ajustar.

### `hover`

Emitido no `mouseleave` de elementos cobertos pelo `hoverSelector`.

| campo | tipo | descricao |
|---|---|---|
| `elemento_id` | string | |
| `elemento_tipo` | string | |
| `duracao_ms` | number | tempo entre `mouseenter` e `mouseleave` |

Por que coletar: indecisao, zonas de atencao sem clique.

### `element_exposure`

Emitido quando o elemento sai do viewport (`IntersectionObserver`). Se `parar()` ocorre com elementos ainda visiveis, emite com a duracao ate aquele momento.

| campo | tipo | descricao |
|---|---|---|
| `elemento_id` | string | |
| `duracao_ms` | number | tempo total que o elemento ficou visivel nesta janela |
| `percent_visivel_max` | number? | maior porcentagem observada de interseccao |

Por que coletar: impressoes de CTAs, consumo de conteudo abaixo da dobra, decisao sobre reordenar secoes.

### `web_vital`

Emitido pela lib `web-vitals` quando a metrica esta pronta. Requer `iniciarAnalytics({ coletarPerformance: true })` (default).

| campo | tipo | descricao |
|---|---|---|
| `nome` | `'LCP' \| 'CLS' \| 'INP'` | nome da metrica Web Vital |
| `valor` | number | valor bruto |
| `rating` | `'good' \| 'needs-improvement' \| 'poor'`? | classificacao do web-vitals |
| `id` | string? | id interno do web-vitals |

Por que coletar: performance percebida, priorizacao de otimizacao por pagina. Persistido num measurement separado (`web_vitals`) no InfluxDB.

### `custom`

Emitido via `enviarEvento(nome, propriedades?)`.

| campo | tipo | descricao |
|---|---|---|
| `nome` | string | identificador de negocio, ate 64 chars |
| `propriedades` | Record<string, primitivo> | chaves e valores primitivos; objetos/arrays/funcoes sao descartados |

Por que coletar: eventos de negocio (`checkout_iniciado`, `plano_selecionado`). Nao fica em `TemporalMetric` como contagem agregada.

## Contagem no backend

O handler agrega por tipo em `TemporalMetric`:

- `cliques` = contagem de `click`
- `toques` = contagem de `touch`
- `scrolls` = contagem de `scroll_depth`
- `mouse_moves` = contagem de `mouse_move`
- `hovers` = contagem de `hover`
- `exposicoes` = contagem de `element_exposure`
- `custom_events` = contagem de `custom`

`page_view` e `page_exit` sao informacionais — o campo `visualizacoes` vem direto do contador da janela, nao de contagem de `page_view`.

Eventos `web_vital` sao gravados separadamente em `Point("web_vitals")`.
