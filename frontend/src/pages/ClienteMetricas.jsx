import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../styles/cliente.css';

const API_BASE = import.meta.env.VITE_API_URL || '';
const GRAFANA_URL = import.meta.env.VITE_GRAFANA_URL || 'http://localhost:3001';
const REDIRECT_DELAY_MS = 1200;

/**
 * Em producao: o nginx do host intercepta /cliente/metricas/* via auth_request
 * e faz proxy direto pro Grafana — este componente nem e renderizado.
 * Em dev local (sem nginx): valida sessao e auto-redireciona pro Grafana
 * standalone, simulando a experiencia de produzao.
 */
export default function ClienteMetricas() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [estado, setEstado] = useState('verificando');

  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/cliente/auth/me`, {
          credentials: 'include',
        });
        if (cancelado) return;
        if (r.status === 401) {
          navigate('/cliente/login?expirado=1', { replace: true });
          return;
        }
        if (r.ok) {
          setUser(await r.json());
          setEstado('redirecionando');
          return;
        }
        setEstado('erro');
      } catch {
        if (!cancelado) setEstado('erro');
      }
    })();
    return () => { cancelado = true; };
  }, [navigate]);

  // Redireciona pro Grafana apos validar sessao (com pequeno delay
  // pra dar tempo do user ler "Sessao ativa para ..." e cancelar se quiser).
  useEffect(() => {
    if (estado !== 'redirecionando') return;
    const t = setTimeout(() => {
      window.location.href = GRAFANA_URL;
    }, REDIRECT_DELAY_MS);
    return () => clearTimeout(t);
  }, [estado]);

  async function sair() {
    await fetch(`${API_BASE}/cliente/auth/logout`, {
      method: 'POST', credentials: 'include',
    });
    navigate('/cliente/login', { replace: true });
  }

  if (estado === 'verificando') {
    return (
      <div className="cliente-metricas-loading">
        <div className="cliente-metricas-spinner" aria-hidden="true" />
        <p>Validando sessao…</p>
      </div>
    );
  }

  if (estado === 'erro') {
    return (
      <div className="cliente-metricas-loading">
        <p>Nao foi possivel validar sua sessao.</p>
        <a href="/cliente/login" style={{ color: '#a855f7' }}>Tentar novamente</a>
      </div>
    );
  }

  // estado === 'redirecionando'
  return (
    <div className="cliente-metricas-loading">
      <div className="cliente-metricas-spinner" aria-hidden="true" />
      <p>
        Bem-vindo, <strong>{user?.email}</strong>.
      </p>
      <p style={{ opacity: 0.7, fontSize: '0.875rem' }}>
        Abrindo seu dashboard…
      </p>
      <p style={{ opacity: 0.5, fontSize: '0.75rem', maxWidth: 480 }}>
        Se nao for redirecionado em alguns segundos,{' '}
        <a href={GRAFANA_URL} style={{ color: '#a855f7' }}>clique aqui</a>.
      </p>
      <button
        onClick={sair}
        style={{
          marginTop: 32, padding: '8px 16px', background: 'transparent',
          border: '1px solid rgba(248,250,252,0.15)', color: 'rgba(248,250,252,0.55)',
          borderRadius: 8, cursor: 'pointer', font: 'inherit', fontSize: '0.8125rem',
        }}
      >
        Sair
      </button>
    </div>
  );
}
