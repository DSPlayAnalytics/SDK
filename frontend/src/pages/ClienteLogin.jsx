import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import '../styles/cliente.css';

const API_BASE = import.meta.env.VITE_API_URL || '';

const MODOS = {
  MAGIC: 'magic',
  SENHA: 'senha',
};

export default function ClienteLogin() {
  const [modo, setModo] = useState(MODOS.MAGIC);
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [estado, setEstado] = useState('idle');   // idle | enviando | sucesso | erro
  const [mensagemErro, setMensagemErro] = useState('');
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const emailRef = useRef(null);

  useEffect(() => {
    document.title = 'Acesso ao dashboard · Playground';
    emailRef.current?.focus();
  }, []);

  // Mensagem amigavel ao chegar na tela apos um magic-link expirado.
  useEffect(() => {
    if (params.get('expirado') === '1') {
      setMensagemErro('Seu link expirou ou ja foi utilizado. Solicite outro abaixo.');
      setEstado('erro');
    }
  }, [params]);

  async function enviarMagicLink(e) {
    e.preventDefault();
    setEstado('enviando');
    setMensagemErro('');
    try {
      const r = await fetch(`${API_BASE}/cliente/auth/magic-link/solicitar`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
      if (r.status === 429) {
        setMensagemErro('Muitas solicitacoes. Tente de novo em 15 minutos.');
        setEstado('erro');
        return;
      }
      // 200 sempre — anti-enumeracao. Mostra mensagem neutra.
      setEstado('sucesso');
    } catch {
      setMensagemErro('Falha de rede. Tente novamente.');
      setEstado('erro');
    }
  }

  async function entrarComSenha(e) {
    e.preventDefault();
    setEstado('enviando');
    setMensagemErro('');
    try {
      const r = await fetch(`${API_BASE}/cliente/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), senha }),
      });
      if (r.ok) {
        navigate('/cliente/metricas', { replace: true });
        return;
      }
      const body = await r.json().catch(() => ({}));
      if (r.status === 401) {
        setMensagemErro('E-mail ou senha incorretos.');
      } else if (r.status === 400) {
        setMensagemErro(body.message || 'Preencha e-mail e senha.');
      } else {
        setMensagemErro('Nao foi possivel entrar. Tente novamente em instantes.');
      }
      setEstado('erro');
    } catch {
      setMensagemErro('Falha de rede. Tente novamente.');
      setEstado('erro');
    }
  }

  const enviando = estado === 'enviando';
  const sucessoMagic = estado === 'sucesso' && modo === MODOS.MAGIC;

  return (
    <div className="cliente-login-root">
      <main className="cliente-login-card" aria-labelledby="cliente-login-titulo">
        <header className="cliente-login-brand">
          <div className="cliente-login-logo" aria-hidden="true">📊</div>
          <h1 id="cliente-login-titulo" className="cliente-login-title">
            Dashboard de metricas
          </h1>
          <p className="cliente-login-subtitle">
            Acesse os dados de analytics do seu site.
          </p>
        </header>

        <div role="tablist" aria-label="Modo de acesso" className="cliente-login-tabs">
          <button
            type="button"
            role="tab"
            aria-selected={modo === MODOS.MAGIC}
            className={`cliente-login-tab ${modo === MODOS.MAGIC ? 'cliente-login-tab--active' : ''}`}
            onClick={() => { setModo(MODOS.MAGIC); setEstado('idle'); setMensagemErro(''); }}
          >
            Link por e-mail
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={modo === MODOS.SENHA}
            className={`cliente-login-tab ${modo === MODOS.SENHA ? 'cliente-login-tab--active' : ''}`}
            onClick={() => { setModo(MODOS.SENHA); setEstado('idle'); setMensagemErro(''); }}
          >
            Senha
          </button>
        </div>

        {modo === MODOS.MAGIC && !sucessoMagic && (
          <form className="cliente-login-form" onSubmit={enviarMagicLink} noValidate>
            <div className="cliente-login-field">
              <label className="cliente-login-label" htmlFor="cliente-email-magic">
                E-mail
              </label>
              <input
                ref={emailRef}
                id="cliente-email-magic"
                className="cliente-login-input"
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder="seu@email.com"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={enviando}
              />
            </div>

            {estado === 'erro' && mensagemErro && (
              <p role="alert" className="cliente-login-error">{mensagemErro}</p>
            )}

            <button
              type="submit"
              className="cliente-login-submit"
              disabled={enviando || !email.trim()}
            >
              {enviando ? 'Enviando…' : 'Receber link de acesso'}
            </button>
          </form>
        )}

        {sucessoMagic && (
          <div role="status" className="cliente-login-success">
            <strong>Verifique sua caixa de entrada.</strong>
            <br />
            Se o e-mail estiver cadastrado, enviamos um link valido por 15 minutos.
            Pode fechar esta aba.
          </div>
        )}

        {modo === MODOS.SENHA && (
          <form className="cliente-login-form" onSubmit={entrarComSenha} noValidate>
            <div className="cliente-login-field">
              <label className="cliente-login-label" htmlFor="cliente-email-senha">
                E-mail
              </label>
              <input
                ref={modo === MODOS.SENHA ? emailRef : null}
                id="cliente-email-senha"
                className="cliente-login-input"
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder="seu@email.com"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={enviando}
              />
            </div>

            <div className="cliente-login-field">
              <label className="cliente-login-label" htmlFor="cliente-senha">
                Senha
              </label>
              <input
                id="cliente-senha"
                className="cliente-login-input"
                type="password"
                autoComplete="current-password"
                placeholder="********"
                required
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                disabled={enviando}
              />
            </div>

            {estado === 'erro' && mensagemErro && (
              <p role="alert" className="cliente-login-error">{mensagemErro}</p>
            )}

            <button
              type="submit"
              className="cliente-login-submit"
              disabled={enviando || !email.trim() || !senha}
            >
              {enviando ? 'Entrando…' : 'Entrar'}
            </button>
          </form>
        )}

        <footer className="cliente-login-footer">
          <Link to="/">← Voltar ao site</Link>
          {modo === MODOS.SENHA && (
            <button
              type="button"
              onClick={() => { setModo(MODOS.MAGIC); setEstado('idle'); }}
              style={{
                background: 'transparent', border: 0, color: 'rgba(248,250,252,0.55)',
                cursor: 'pointer', font: 'inherit', padding: '4px 0',
              }}
            >
              Esqueci a senha
            </button>
          )}
        </footer>
      </main>
    </div>
  );
}
