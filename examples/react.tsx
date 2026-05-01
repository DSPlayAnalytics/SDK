// Exemplo React + react-router-dom — pagina = rota.
// Funciona em CRA, Vite, Next.js (use client), Remix, etc — qualquer projeto
// React com bundler ESM.
//
// Pre-requisito: ter o pacote instalado via npm/yarn/pnpm.
//
//   # com .npmrc apontando pro GitHub Packages e NODE_AUTH_TOKEN exportado:
//   npm install @danpqdan/dsplayground-analytics-sdk
//   npm install react-router-dom
//
// Padrao adotado:
//  - `iniciarAnalytics` no module-load (App.tsx top-level), uma unica vez.
//  - `enviarEvento('app_carregado')` ANTES de qualquer route mount —
//    exercita o buffer pre-iniciar (v0.3.1+); o evento fica enfileirado
//    em buffer global (cap 100) e e drenado pra primeira pagina ativa.
//  - Hook `useAnalyticsPagina(pageId)` por rota — cria HeatmapUtils no mount
//    e chama `parar()` no unmount. Isso garante page_view + page_exit
//    automaticos a cada troca de rota.

import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import {
  iniciarAnalytics,
  HeatmapUtils,
  WebSocketService,
  enviarEvento,
} from '@danpqdan/dsplayground-analytics-sdk';

// ---------- 1. Inicializacao (uma unica vez no module-load) ----------
// `publishableKey` (opcional em dev sem auth, OBRIGATORIO em prod) vem do
// backend via scripts/tenant_admin create-key — vinculada ao site_id do
// cliente. SDK troca essa key por sdk_jwt de 5 min antes de cada conexao
// Socket.IO; eventos sao roteados pro bucket dedicado do cliente.
iniciarAnalytics({
  websocketUrl: 'https://api.dsplayground.com.br',
  publishableKey: 'pk_production_xxxxx', // deixar vazio em dev local sem auth
  appId: 'minha-spa-react',
  ambiente: 'production',
  debug: false,
  intervaloEnvioMs: 5000,
  coletarPerformance: true,
  taxaAmostragemMouseMove: 5,
});

// ---------- 2. Evento de boot ANTES de qualquer route mount ----------
// `enviarEvento` aqui exercita o buffer pre-iniciar (v0.3.1+): o evento
// fica enfileirado num buffer global (cap 100) e e drenado pra primeira
// pagina ativa quando `useAnalyticsPagina` montar abaixo. Isso e util
// porque, no top-level do App, ainda nao existe HeatmapUtils ativo —
// sem o buffer o evento seria descartado.
enviarEvento('app_carregado', {
  rota_inicial: window.location.pathname || '/',
  viewport_largura: window.innerWidth,
});

// ---------- 3. Hook de coleta por pagina ----------
// Use em cada componente de rota. O `pageId` deve identificar a pagina
// (ex.: '/checkout', 'home', 'produto:123') — vai pro field `page_type`
// do payload e e a chave que o backend usa pra agregar.
//
// `hoverSelector` e opcional. Quando passado, hovers em elementos que
// casam com o seletor sao registrados (mouseleave dispara o evento com
// duracao). Sem seletor, hovers nao sao coletados.
export function useAnalyticsPagina(pageId: string, hoverSelector?: string) {
  useEffect(() => {
    const heatmap = new HeatmapUtils(
      document.body,
      hoverSelector ?? '[data-analytics-id], a, button',
      pageId,
    );

    heatmap.configurarColecaoTempoReal((dados) => {
      WebSocketService.sendAnalyticsDataImmediate(dados, false);
    }, 5000);

    heatmap.iniciarColecaoTempoReal();
    heatmap.iniciar();

    // Cleanup: emite page_exit com duracao_ms e motivo='unmount',
    // drena o residuo final, solta os listeners DOM. Sem isso, troca
    // de rota perde o ultimo intervalo de eventos.
    return () => heatmap.parar('unmount');
  }, [pageId, hoverSelector]);
}

// ---------- 4. Paginas ----------

function Home() {
  useAnalyticsPagina('/');

  return (
    <main>
      <h1>Home</h1>
      <p>Bem-vindo a landing page.</p>
      <Link to="/produto" data-analytics-id="link-produto">Ver produto</Link>
    </main>
  );
}

function Produto() {
  useAnalyticsPagina('/produto');

  const handleComprar = () => {
    // Eventos de negocio. So primitivos sao aceitos em propriedades.
    enviarEvento('checkout_iniciado', {
      plano: 'pro',
      preco: 99.9,
      recorrente: true,
    });
  };

  return (
    <main>
      <h1>Produto Pro</h1>
      <button data-analytics-id="cta-comprar" onClick={handleComprar}>
        Comprar agora
      </button>
      <Link to="/contato" data-analytics-id="link-contato">Falar com vendas</Link>
    </main>
  );
}

function Contato() {
  useAnalyticsPagina('/contato');

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    // Nao envie PII como email/telefone aqui — se precisar correlacionar,
    // hashear antes ou usar identificador pseudonimizado.
    enviarEvento('formulario_enviado', {
      formulario_id: 'contato',
    });
  };

  return (
    <main>
      <h1>Contato</h1>
      <form id="contato" onSubmit={handleSubmit}>
        <input type="text" name="nome" placeholder="Seu nome" />
        <button type="submit" data-analytics-id="form-contato-submit">
          Enviar
        </button>
      </form>
    </main>
  );
}

// ---------- 5. (Opcional) Tracking de pageview manual em apps que ----------
// fazem navegacao sem desmontar o componente de rota.
//
// Em alguns padroes (ex.: animacoes de transicao com framer-motion que
// preservam o componente), o `useAnalyticsPagina` no nivel da rota nao
// remonta entre paginas. Nesse caso, use este hook num componente alto
// na arvore (App ou Layout) e pule o useAnalyticsPagina nas rotas:
export function useAnalyticsRotaGlobal() {
  const location = useLocation();
  useAnalyticsPagina(location.pathname);
}

// ---------- 6. App ----------

export default function App() {
  return (
    <BrowserRouter>
      <nav>
        <Link to="/">Home</Link>
        {' | '}
        <Link to="/produto">Produto</Link>
        {' | '}
        <Link to="/contato">Contato</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/produto" element={<Produto />} />
        <Route path="/contato" element={<Contato />} />
      </Routes>
    </BrowserRouter>
  );
}
