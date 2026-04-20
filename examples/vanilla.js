// Exemplo de uso do SDK em JavaScript puro, sem React ou framework.
// Quando o SDK for publicado como pacote, a unica mudanca e o import:
//   import { iniciarAnalytics, HeatmapUtils, WebSocketService, enviarEvento } from '@seu-escopo/analytics-sdk';

import { iniciarAnalytics, HeatmapUtils, WebSocketService, enviarEvento } from '../index.ts';

// ---------- 1. Inicializacao (uma unica vez no boot) ----------
iniciarAnalytics({
  websocketUrl: 'http://localhost:5000',
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
