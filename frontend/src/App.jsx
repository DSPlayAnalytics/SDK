import { useEffect, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import BackGround from "./BackGround";
import SlidesCarousel from './components/SlidesCarousel';
import Home from './pages/Home';
import Projects from './pages/Projects';
import About from './pages/About';
import ClienteLogin from './pages/ClienteLogin';
import ClienteMetricas from './pages/ClienteMetricas';
import EmbedWidget from './pages/EmbedWidget';
import { iniciarAnalytics, enviarEvento, trackConversion } from '@dsplayground-analytics/sdk';
import { WEBSOCKET_URL, DEBUG_ENABLED, NODE_ENV, PUBLISHABLE_KEY } from './config.js';

const AMBIENTES_SUPORTADOS = ['development', 'test', 'staging', 'production'];
const ambiente = AMBIENTES_SUPORTADOS.includes(NODE_ENV) ? NODE_ENV : 'development';

// /widget/* serve o widget de embed (consumidor de dados). SDK de analytics
// nao deve rodar la — nao tem o que medir e dispara 403 em /auth/sdk-token
// + viola CSP connect-src do vhost embed.X. Guard antes do init.
const ehRotaWidget = typeof window !== 'undefined'
  && window.location.pathname.startsWith('/widget/');

if (!ehRotaWidget) {
  iniciarAnalytics({
    websocketUrl: WEBSOCKET_URL,
    appId: 'portfolio-local',
    ambiente,
    debug: DEBUG_ENABLED,
    intervaloEnvioMs: 5000,
    // Em dev local pode ficar vazio (SDK roda sem auth, dados no bucket default).
    // Pra rotear pra um bucket de cliente real, defina VITE_PUBLISHABLE_KEY no
    // .env ou docker-compose com a key gerada por scripts.tenant_admin create-key.
    ...(PUBLISHABLE_KEY ? { publishableKey: PUBLISHABLE_KEY } : {}),
  });
}

function Portfolio() {
  const [showUi, setShowUi] = useState(false);

  useEffect(() => {
    const onTorreStarted = () => {
      setShowUi(true);
      // Custom event de exemplo: alimenta o dashboard Event Explorer com
      // dados reais. Em prod cada cliente substitui por chamadas relevantes
      // (checkout_iniciado, formulario_enviado, video_play, etc.).
      enviarEvento('app_carregado', {
        rota_inicial: window.location.pathname,
        viewport_width: window.innerWidth,
      });
      trackConversion('portfolio_load', undefined, {
        rota: window.location.pathname,
      });
    };
    window.addEventListener('torre:started', onTorreStarted);

    const handleBeforeUnload = () => {
      const controller = window.__ACTIVE_PAGE_CONTROLLER__;
      if (controller && typeof controller.parar === 'function') {
        controller.parar();
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('torre:started', onTorreStarted);
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, []);

  return (
    <div id="app" style={{
      height: '100dvh', width: '100vw', overflow: 'hidden', position: 'relative', display: 'flex'
   }}>
      <BackGround />
      {showUi && (
        <div style={{ position: 'relative', zIndex: 20000, width: '100%' }}>
          <SlidesCarousel slides={[
            { path: '/',         label: 'Início',   element: <Home /> },
            { path: '/projects', label: 'Projetos', element: <Projects /> },
            { path: '/about',    label: 'Sobre',    element: <About /> },
          ]} />
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/cliente/login" element={<ClienteLogin />} />
      <Route path="/cliente/metricas/*" element={<ClienteMetricas />} />
      <Route path="/widget/:siteId/:graficoId" element={<EmbedWidget />} />
      <Route path="*" element={<Portfolio />} />
    </Routes>
  );
}
