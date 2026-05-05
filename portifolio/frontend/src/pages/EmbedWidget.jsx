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

function postParaParent(mensagem) {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage(mensagem, '*');
  }
}

async function fetchDados(siteId, graficoId, token) {
  const url = `${API_URL.replace(/\/$/, '')}/embed/dados/${siteId}/${graficoId}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return resp;
}

export default function EmbedWidget() {
  const { siteId, graficoId } = useParams();
  const [searchParams] = useSearchParams();
  const tokenInicial = searchParams.get('token') || '';

  const [token, setToken] = useState(tokenInicial);
  const [estado, setEstado] = useState(ESTADO.CARREGANDO);
  const [pontos, setPontos] = useState([]);
  const inicioRef = useRef(performance.now());

  useEffect(() => {
    function onMensagem(ev) {
      if (!ev.data || typeof ev.data !== 'object') return;
      if (ev.data.tipo === 'embed.token_renovado' && typeof ev.data.token === 'string') {
        setToken(ev.data.token);
      }
    }
    window.addEventListener('message', onMensagem);
    return () => window.removeEventListener('message', onMensagem);
  }, []);

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
          postParaParent({
            tipo: 'embed.erro',
            codigo: 'erro_servidor',
            status: resp.status,
          });
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

    return () => {
      cancelado = true;
    };
  }, [siteId, graficoId, token]);

  const chartData = useMemo(() => {
    const labels = pontos.map((p) => p.page_type || 'desconhecido');
    const valores = pontos.map((p) => Number(p?.totais?.visualizacoes || 0));
    return {
      labels,
      datasets: [
        {
          label: 'Visualizações',
          data: valores,
          backgroundColor: 'rgba(99, 102, 241, 0.7)',
          borderColor: 'rgba(99, 102, 241, 1)',
          borderWidth: 1,
        },
      ],
    };
  }, [pontos]);

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top' },
        title: { display: false },
      },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    }),
    [],
  );

  return (
    <div
      style={{
        height: '100dvh',
        width: '100vw',
        padding: 12,
        background: '#0b0b14',
        color: '#e6e6f0',
        fontFamily: 'system-ui, sans-serif',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
      }}
      data-testid="embed-widget"
    >
      {estado === ESTADO.CARREGANDO && (
        <p role="status" style={{ margin: 0 }}>Carregando…</p>
      )}
      {estado === ESTADO.ERRO_TOKEN && (
        <p role="alert" style={{ margin: 0, color: '#f87171' }}>
          Sessão de embed expirada. Recarregue para reautenticar.
        </p>
      )}
      {estado === ESTADO.ERRO_REDE && (
        <p role="alert" style={{ margin: 0, color: '#fbbf24' }}>
          Não foi possível carregar os dados.
        </p>
      )}
      {estado === ESTADO.SEM_DADOS && (
        <p role="status" style={{ margin: 0 }}>Sem dados no período.</p>
      )}
      {estado === ESTADO.PRONTO && (
        <div style={{ flex: 1, minHeight: 0 }} data-testid="embed-grafico">
          <Bar data={chartData} options={chartOptions} />
        </div>
      )}
    </div>
  );
}
