import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';
import { API_URL } from '../config.js';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const ESTADO = {
  CARREGANDO: 'carregando',
  PRONTO: 'pronto',
  ERRO_TOKEN: 'erro_token',
  ERRO_REDE: 'erro_rede',
  SEM_DADOS: 'sem_dados',
};

// Tokens alinhados com o design system do landing (slate + brand azul)
const C = {
  bg:        '#0b0f1a',
  bgBar:     '#111827',
  borda:     'rgba(148,163,184,0.12)',
  texto:     '#cbd5e1',
  muted:     '#64748b',
  marca:     '#549cf0',
  marcaBg:   'rgba(84,156,240,0.7)',
  perigo:    '#f87171',
  aviso:     '#fbbf24',
  grade:     'rgba(148,163,184,0.07)',
  tooltip:   '#1a2235',
};

const SKELETON_ALTS = [60, 40, 80, 55, 70, 45, 65, 50, 75, 30, 60, 50];

const CSS_EMBED = `
  @keyframes embed-pulse {
    0%,100% { opacity:.35; }
    50%      { opacity:.75; }
  }
`;

function postParaParent(mensagem) {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage(mensagem, '*');
  }
}

async function fetchDados(siteId, graficoId, token) {
  const url = `${API_URL.replace(/\/$/, '')}/embed/dados/${siteId}/${graficoId}`;
  return fetch(url, { headers: { Authorization: `Bearer ${token}` } });
}

function Skeleton() {
  return (
    <div role="status" style={{ display:'flex', alignItems:'flex-end', gap:6, height:'100%', padding:'4px 0' }}>
      <span style={{ position:'absolute', width:1, height:1, padding:0, margin:-1, overflow:'hidden', clip:'rect(0,0,0,0)', whiteSpace:'nowrap', borderWidth:0 }}>Carregando</span>
      {SKELETON_ALTS.map((h, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${h}%`,
            borderRadius: '4px 4px 0 0',
            background: C.bgBar,
            border: `1px solid ${C.borda}`,
            animation: `embed-pulse 1.4s ease-in-out ${(i * 0.08).toFixed(2)}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

function Estado({ icone, titulo, descricao, cor, role }) {
  return (
    <div role={role} style={{
      display:'flex', flexDirection:'column', alignItems:'center',
      justifyContent:'center', height:'100%', gap:8,
      textAlign:'center', padding:'0 20px',
    }}>
      <span style={{ fontSize:28 }} role="img" aria-hidden="true">{icone}</span>
      <p style={{ margin:0, fontWeight:600, fontSize:14, color: cor ?? C.texto }}>{titulo}</p>
      {descricao && (
        <p style={{ margin:0, fontSize:12, color: C.muted, lineHeight:1.5 }}>{descricao}</p>
      )}
    </div>
  );
}

export default function EmbedWidget() {
  const { siteId, graficoId } = useParams();
  const [searchParams] = useSearchParams();
  const tokenInicial = searchParams.get('token') || '';

  const [token, setToken] = useState(tokenInicial);
  const [estado, setEstado] = useState(ESTADO.CARREGANDO);
  const [pontos, setPontos] = useState([]);
  const inicioRef = useRef(performance.now());

  // Injeta CSS de animacao uma unica vez
  useEffect(() => {
    if (!document.getElementById('embed-widget-css')) {
      const el = document.createElement('style');
      el.id = 'embed-widget-css';
      el.textContent = CSS_EMBED;
      document.head.appendChild(el);
    }
  }, []);

  // Escuta renovacao de token enviada pelo host via postMessage
  useEffect(() => {
    function onMsg(ev) {
      if (!ev.data || typeof ev.data !== 'object') return;
      if (ev.data.tipo === 'embed.token_renovado' && typeof ev.data.token === 'string') {
        setToken(ev.data.token);
      }
    }
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, []);

  // Carrega dados quando token/grafico muda
  useEffect(() => {
    let cancelado = false;
    if (!token) {
      setEstado(ESTADO.ERRO_TOKEN);
      postParaParent({ tipo: 'embed.erro', codigo: 'sem_token' });
      return () => {};
    }

    setEstado(ESTADO.CARREGANDO);
    fetchDados(siteId, graficoId, token)
      .then(async (resp) => {
        if (cancelado) return;
        if (resp.status === 401) {
          setEstado(ESTADO.ERRO_TOKEN);
          postParaParent({ tipo: 'embed.token_expirado' });
          return;
        }
        if (!resp.ok) {
          setEstado(ESTADO.ERRO_REDE);
          postParaParent({ tipo: 'embed.erro', codigo: 'erro_servidor', status: resp.status });
          return;
        }
        const body = await resp.json();
        const recebidos = Array.isArray(body.pontos) ? body.pontos : [];
        if (recebidos.length === 0) {
          setEstado(ESTADO.SEM_DADOS);
          postParaParent({ tipo: 'embed.erro', codigo: 'sem_dados' });
          return;
        }
        setPontos(recebidos);
        setEstado(ESTADO.PRONTO);
        postParaParent({
          tipo: 'embed.pronto',
          site_id: siteId,
          grafico_id: graficoId,
          render_ms: Math.round(performance.now() - inicioRef.current),
        });
      })
      .catch(() => {
        if (cancelado) return;
        setEstado(ESTADO.ERRO_REDE);
        postParaParent({ tipo: 'embed.erro', codigo: 'erro_rede' });
      });

    return () => { cancelado = true; };
  }, [siteId, graficoId, token]);

  const chartData = useMemo(() => ({
    labels: pontos.map((p) => p.page_type || 'desconhecido'),
    datasets: [{
      label: 'Visualizações',
      data: pontos.map((p) => Number(p?.totais?.visualizacoes || 0)),
      backgroundColor: C.marcaBg,
      borderColor: C.marca,
      borderWidth: 1,
      borderRadius: 4,
      borderSkipped: false,
    }],
  }), [pontos]);

  const chartOptions = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: { color: C.texto, boxWidth: 12, font: { size: 12 } },
      },
      title: { display: false },
      tooltip: {
        backgroundColor: C.tooltip,
        titleColor: C.texto,
        bodyColor: C.muted,
        borderColor: C.borda,
        borderWidth: 1,
        padding: 10,
        cornerRadius: 6,
      },
    },
    scales: {
      x: {
        ticks: { color: C.muted, font: { size: 11 } },
        grid: { color: C.grade },
        border: { color: C.borda },
      },
      y: {
        beginAtZero: true,
        ticks: { precision: 0, color: C.muted, font: { size: 11 } },
        grid: { color: C.grade },
        border: { color: C.borda },
      },
    },
  }), []);

  return (
    <div
      style={{
        height: '100dvh',
        width: '100vw',
        padding: 16,
        background: C.bg,
        color: C.texto,
        fontFamily: '"Inter", system-ui, sans-serif',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
      }}
      data-testid="embed-widget"
    >
      {estado === ESTADO.CARREGANDO && <Skeleton />}

      {estado === ESTADO.ERRO_TOKEN && (
        <Estado
          role="alert"
          icone="🔒"
          titulo="Sessão expirada"
          descricao="Recarregue a página para continuar"
          cor={C.perigo}
        />
      )}

      {estado === ESTADO.ERRO_REDE && (
        <Estado
          role="alert"
          icone="⚠️"
          titulo="Não foi possível carregar"
          descricao="Verifique sua conexão e tente novamente"
          cor={C.aviso}
        />
      )}

      {estado === ESTADO.SEM_DADOS && (
        <Estado
          role="status"
          icone="📊"
          titulo="Sem dados no período"
          descricao="Quando chegarem eventos, o gráfico aparece aqui"
        />
      )}

      {estado === ESTADO.PRONTO && (
        <div style={{ flex: 1, minHeight: 0 }} data-testid="embed-grafico">
          <Bar data={chartData} options={chartOptions} />
        </div>
      )}
    </div>
  );
}
