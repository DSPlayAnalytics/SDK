// Exemplo ESM (com bundler) — para Vite, Webpack, esbuild, Rollup, Parcel.
// Funciona em projetos JS/TS sem framework de UI (vanilla = sem React/Vue/etc),
// mas com pipeline de build moderna que resolve `import` ESM.
//
// Pre-requisito: ter o pacote instalado via npm/yarn/pnpm.
//
//   # com .npmrc apontando pro GitHub Packages e NODE_AUTH_TOKEN exportado:
//   npm install @danpqdan/dsplayground-analytics-sdk
//
// Para uso TRULY vanilla (HTML estatico sem bundler, ex: Webflow/Wix-like),
// ver examples/standalone.html — usa o bundle UMD via <script src="">.

import {
  iniciarAnalytics,
  HeatmapUtils,
  WebSocketService,
  enviarEvento,
} from '@danpqdan/dsplayground-analytics-sdk';

// ---------- 1. Inicializacao (uma unica vez no boot) ----------
//
// `publishableKey` (opcional em dev sem auth, OBRIGATORIO em prod) vem do
// backend via scripts/tenant_admin create-key — vinculada ao site_id do
// cliente. SDK troca essa key por sdk_jwt de 5 min antes de cada conexao
// Socket.IO; eventos sao roteados pro bucket dedicado do cliente.
iniciarAnalytics({
  websocketUrl: 'https://api.dsplayground.com.br',
  publishableKey: 'pk_production_xxxxx', // deixar vazio em dev local sem auth
  appId: 'minha-landing',
  ambiente: 'production',
  debug: false,
  intervaloEnvioMs: 5000,
  coletarPerformance: true,
  taxaAmostragemMouseMove: 5,
});

// ---------- 2. Coleta automatica por pagina ----------
// Em SPA, instancie um HeatmapUtils por rota e controle iniciar/parar ao trocar de pagina.
// Em pagina estatica, basta iniciar no DOMContentLoaded e parar no beforeunload.

let heatmap = null;

function iniciarColeta(pageId) {
  heatmap = new HeatmapUtils(
    document.body,
    '[data-analytics-id], a, button', // seletor de elementos rastreados para hover
    pageId,
  );

  heatmap.configurarColecaoTempoReal((dados) => {
    WebSocketService.sendAnalyticsDataImmediate(dados, false);
  }, 5000);

  heatmap.iniciarColecaoTempoReal();
  heatmap.iniciar();
}

function pararColeta(motivo = 'unmount') {
  if (heatmap) {
    heatmap.parar(motivo); // emite page_exit e residuo final automaticamente
    heatmap = null;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  iniciarColeta(window.location.pathname || '/');
});

window.addEventListener('beforeunload', () => {
  pararColeta('aba_fechada');
});

// ---------- 3. Navegacao entre paginas (SPA sem router) ----------
// Quando o usuario troca de pagina programaticamente, chame pararColeta -> iniciarColeta.

function navegarPara(novoPath) {
  pararColeta('navegacao');
  window.history.pushState({}, '', novoPath);
  iniciarColeta(novoPath);
}

// ---------- 4. Eventos de negocio ----------
// Chame enviarEvento em pontos-chave do funil. So primitivos sao aceitos em propriedades.

document.querySelector('[data-analytics-id="cta-comprar"]')?.addEventListener('click', () => {
  enviarEvento('checkout_iniciado', {
    plano: 'pro',
    preco: 99.9,
    recorrente: true,
  });
});

document.querySelector('form#contato')?.addEventListener('submit', () => {
  const tempoMs = performance.now() - (window.__contato_inicio__ ?? performance.now());
  enviarEvento('formulario_enviado', {
    formulario_id: 'contato',
    tempo_preenchimento_ms: Math.round(tempoMs),
    // Nao envie PII como email/telefone; se precisar, hashear antes.
  });
});

// Exporta helpers para uso externo se precisar.
export { iniciarColeta, pararColeta, navegarPara };
