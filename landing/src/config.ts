export const SITE_NAME = 'DS Playground Analytics';
export const SITE_URL = import.meta.env.PUBLIC_SITE_URL || 'https://dsplayground.com.br';
export const API_URL = import.meta.env.PUBLIC_API_URL || 'https://api.dsplayground.com.br';

// DASHBOARD_URL: atalho pra "ver minhas metricas". Aponta pro Grafana
// embedado em app.X. Usado no botao "Painel" do Nav (logged-aware) e em
// links que querem levar pro analytico.
export const DASHBOARD_URL = import.meta.env.PUBLIC_DASHBOARD_URL || 'https://app.dsplayground.com.br/cliente/metricas';

// POS_LOGIN_URL: destino default apos login/cadastro bem-sucedido (quando
// nao ha `?next=` valido). Aponta pra Configuracoes — cliente recem-logado
// ve publishable_key, plano, consumo antes de ir pro dashboard analitico.
// Pra mudar o comportamento, setar `PUBLIC_POS_LOGIN_URL` em CF Pages.
export const POS_LOGIN_URL = import.meta.env.PUBLIC_POS_LOGIN_URL || 'https://dsplayground.com.br/cliente/configuracoes/';

export const PUBLISHABLE_KEY = import.meta.env.PUBLIC_PUBLISHABLE_KEY || '';
export const DEBUG = import.meta.env.PUBLIC_DEBUG === 'true';
