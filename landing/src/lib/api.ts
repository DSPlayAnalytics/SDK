/**
 * Cliente HTTP do landing -> api.dsplayground.com.br.
 *
 * Endpoints de auth humana retornam JSON com forma:
 *   sucesso: { status: 'success', user, site? }
 *   erro:    { status: 'error', code, message }
 *
 * Aqui tipamos os codes conhecidos e retornamos um discriminated union
 * `Result<T>` para o caller fazer narrowing por `r.ok`. Cookies de sessao
 * sao gerenciados pelo browser (HttpOnly), portanto sempre `credentials: 'include'`.
 */

export interface CadastroPayload {
  email: string;
  senha: string;
  nome_site: string;
  slug: string;
}

export interface LoginPayload {
  email: string;
  senha: string;
}

export interface UserDto {
  id: string;
  site_id: string;
  email: string;
  papel: string;
}

export interface SiteDto {
  id: string;
  slug: string;
  nome: string;
  bucket_name: string | null;
  plano: string;
}

export type CadastroErrorCode =
  | 'PAYLOAD_INCOMPLETO'
  | 'EMAIL_INVALIDO'
  | 'SENHA_CURTA'
  | 'SLUG_INVALIDO'
  | 'EMAIL_JA_CADASTRADO'
  | 'SLUG_JA_CADASTRADO'
  | 'CADASTRO_NAO_CONFIGURADO'
  | 'REDE'
  | 'INESPERADO';

export type LoginErrorCode =
  | 'CREDENCIAIS_INVALIDAS'
  | 'REDE'
  | 'INESPERADO';

export type MagicLinkErrorCode =
  | 'RATE_LIMIT_EXCEDIDO'
  | 'REDE'
  | 'INESPERADO';

export type RecuperarSenhaErrorCode =
  | 'RATE_LIMIT_EXCEDIDO'
  | 'REDE'
  | 'INESPERADO';

export type ConfirmarRecuperarSenhaErrorCode =
  | 'TOKEN_INVALIDO'
  | 'SENHA_CURTA'
  | 'REDE'
  | 'INESPERADO';

export interface SolicitarMagicLinkPayload {
  email: string;
}

export interface MagicLinkOk {
  ok: boolean;
}

export interface ConfirmarRecuperarSenhaOk {
  user: UserDto;
}

export type AlterarSenhaErrorCode =
  | 'NAO_AUTENTICADO'
  | 'SENHA_INVALIDA'
  | 'SENHA_CURTA'
  | 'REDE'
  | 'INESPERADO';

export type AlterarEmailErrorCode =
  | 'NAO_AUTENTICADO'
  | 'SENHA_INVALIDA'
  | 'EMAIL_INVALIDO'
  | 'EMAIL_JA_CADASTRADO'
  | 'REDE'
  | 'INESPERADO';

export interface AlterarOk {
  ok: boolean;
}

export type ListarExportsErrorCode =
  | 'NAO_AUTENTICADO'
  | 'REDE'
  | 'INESPERADO';

export interface ExportItem {
  dia: string;       // 'YYYY-MM-DD'
  key: string;       // '<slug>/YYYY/MM/DD.lp.gz'
}

export interface ListarExportsOk {
  arquivos: ExportItem[];
}

export type ConfiguracoesErrorCode =
  | 'NAO_AUTENTICADO'
  | 'SITE_NAO_ENCONTRADO'
  | 'BACKEND_INCOMPLETO'
  | 'REDE'
  | 'INESPERADO';

export interface PublishableKeyDto {
  key_id: string;
  valor: string;
  nome: string | null;
  ambiente: string;
}

export interface QuotaDto {
  eventos_por_minuto: number;
  eventos_por_dia: number;
  emissoes_jwt_por_minuto: number;
  retencao_dias: number;
}

export interface ConfiguracoesOk {
  user: { id: string; email: string; papel: string };
  site: {
    id: string; slug: string; nome: string; ambiente: string;
    plano: string; bucket_name: string | null;
  };
  publishable_keys: PublishableKeyDto[];
  quota: QuotaDto;
  consumo: { eventos_hoje: number };
  /** Cardinalidade atual e limite do plano. atual=limite=0 quando tracker
   *  nao disponivel (env de teste minimo). */
  cardinalidade: { atual: number; limite: number };
}

export type Result<T, E> =
  | { ok: true } & T
  | { ok: false; code: E; message: string; status: number };

export interface CadastroOk {
  user: UserDto;
  site: SiteDto;
}

export interface LoginOk {
  user: UserDto;
}

export interface ApiOptions {
  apiUrl: string;
  fetchImpl?: typeof fetch;
}

async function postJson<TOk, TErr extends string>(
  url: string,
  body: unknown,
  fetchImpl: typeof fetch,
): Promise<Result<TOk, TErr>> {
  let resp: Response;
  try {
    resp = await fetchImpl(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, code: 'REDE' as TErr, message: 'falha de rede', status: 0 };
  }

  let data: any;
  try {
    data = await resp.json();
  } catch {
    return {
      ok: false,
      code: 'INESPERADO' as TErr,
      message: `resposta nao-JSON (status ${resp.status})`,
      status: resp.status,
    };
  }

  if (resp.ok) {
    const { status: _ignored, ...rest } = data;
    return { ok: true, ...(rest as TOk) };
  }
  return {
    ok: false,
    code: (data?.code ?? 'INESPERADO') as TErr,
    message: data?.message ?? 'erro inesperado',
    status: resp.status,
  };
}

export function cadastrar(
  payload: CadastroPayload,
  opts: ApiOptions,
): Promise<Result<CadastroOk, CadastroErrorCode>> {
  return postJson<CadastroOk, CadastroErrorCode>(
    `${opts.apiUrl}/cliente/auth/cadastro`,
    payload,
    opts.fetchImpl ?? fetch,
  );
}

export function login(
  payload: LoginPayload,
  opts: ApiOptions,
): Promise<Result<LoginOk, LoginErrorCode>> {
  return postJson<LoginOk, LoginErrorCode>(
    `${opts.apiUrl}/cliente/auth/login`,
    payload,
    opts.fetchImpl ?? fetch,
  );
}

/**
 * Solicita magic-link por email. O backend responde 200 anti-enum (mesma
 * resposta pra email valido ou fantasma) — caller nao deve diferenciar
 * sucesso de "email nao existe" pra nao vazar info.
 *
 * 429 = rate limit (10 req/h por IP, 3/h por user).
 */
export function solicitarMagicLink(
  payload: SolicitarMagicLinkPayload,
  opts: ApiOptions,
): Promise<Result<MagicLinkOk, MagicLinkErrorCode>> {
  return postJson<MagicLinkOk, MagicLinkErrorCode>(
    `${opts.apiUrl}/cliente/auth/magic-link/solicitar`,
    payload,
    opts.fetchImpl ?? fetch,
  );
}

async function patchJson<TOk, TErr extends string>(
  url: string,
  body: unknown,
  fetchImpl: typeof fetch,
  codeMap: Partial<Record<number, TErr>> = {},
): Promise<Result<TOk, TErr>> {
  let resp: Response;
  try {
    resp = await fetchImpl(url, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, code: 'REDE' as TErr, message: 'falha de rede', status: 0 };
  }
  let data: any = null;
  try { data = await resp.json(); } catch { /* aceitavel pra 401 vazio */ }
  if (resp.ok) {
    return { ok: true, ...(data as TOk) };
  }
  const code = (data?.code ?? codeMap[resp.status] ?? 'INESPERADO') as TErr;
  return {
    ok: false,
    code,
    message: data?.message ?? `erro ${resp.status}`,
    status: resp.status,
  };
}

async function getJson<TOk, TErr extends string>(
  url: string,
  fetchImpl: typeof fetch,
  codeMap: Partial<Record<number, TErr>>,
): Promise<Result<TOk, TErr>> {
  let resp: Response;
  try {
    resp = await fetchImpl(url, {
      method: 'GET',
      credentials: 'include',
    });
  } catch {
    return { ok: false, code: 'REDE' as TErr, message: 'falha de rede', status: 0 };
  }

  if (resp.ok) {
    let data: any;
    try { data = await resp.json(); }
    catch {
      return {
        ok: false,
        code: 'INESPERADO' as TErr,
        message: `resposta nao-JSON (status ${resp.status})`,
        status: resp.status,
      };
    }
    return { ok: true, ...(data as TOk) };
  }

  const code = codeMap[resp.status] ?? ('INESPERADO' as TErr);
  return {
    ok: false,
    code,
    message: `erro ${resp.status}`,
    status: resp.status,
  };
}

/**
 * Solicita link de redefinição de senha por email (tipo='reset').
 * O backend responde 200 anti-enum — mesma resposta pra email válido ou fantasma.
 * O link enviado redireciona para /cliente/redefinir-senha?t=<token>, NÃO loga.
 */
export function solicitarRecuperarSenha(
  payload: SolicitarMagicLinkPayload,
  opts: ApiOptions,
): Promise<Result<MagicLinkOk, RecuperarSenhaErrorCode>> {
  return postJson<MagicLinkOk, RecuperarSenhaErrorCode>(
    `${opts.apiUrl}/cliente/auth/recuperar-senha/solicitar`,
    payload,
    opts.fetchImpl ?? fetch,
  );
}

/**
 * Confirma redefinição de senha via token do link.
 * Consome o token, troca a senha e abre sessão (Set-Cookie).
 * Codigos: TOKEN_INVALIDO (expirado/usado), SENHA_CURTA (<8 chars).
 */
export function confirmarRecuperarSenha(
  payload: { token: string; nova_senha: string },
  opts: ApiOptions,
): Promise<Result<ConfirmarRecuperarSenhaOk, ConfirmarRecuperarSenhaErrorCode>> {
  return postJson<ConfirmarRecuperarSenhaOk, ConfirmarRecuperarSenhaErrorCode>(
    `${opts.apiUrl}/cliente/auth/recuperar-senha/confirmar`,
    payload,
    opts.fetchImpl ?? fetch,
  );
}

/**
 * Troca senha do user logado.
 * Codigos: SENHA_INVALIDA (atual errada), SENHA_CURTA (<8), NAO_AUTENTICADO.
 */
export function alterarSenha(
  payload: { senha_atual: string; nova_senha: string },
  opts: ApiOptions,
): Promise<Result<AlterarOk, AlterarSenhaErrorCode>> {
  return patchJson<AlterarOk, AlterarSenhaErrorCode>(
    `${opts.apiUrl}/cliente/auth/senha`,
    payload,
    opts.fetchImpl ?? fetch,
    { 401: 'NAO_AUTENTICADO', 403: 'SENHA_INVALIDA', 400: 'SENHA_CURTA' },
  );
}

/**
 * Troca email do user logado.
 * Codigos: SENHA_INVALIDA, EMAIL_INVALIDO, EMAIL_JA_CADASTRADO, NAO_AUTENTICADO.
 */
export function alterarEmail(
  payload: { senha_atual: string; novo_email: string },
  opts: ApiOptions,
): Promise<Result<AlterarOk, AlterarEmailErrorCode>> {
  return patchJson<AlterarOk, AlterarEmailErrorCode>(
    `${opts.apiUrl}/cliente/auth/email`,
    payload,
    opts.fetchImpl ?? fetch,
    {
      401: 'NAO_AUTENTICADO',
      403: 'SENHA_INVALIDA',
      400: 'EMAIL_INVALIDO',
      409: 'EMAIL_JA_CADASTRADO',
    },
  );
}

/**
 * Settings do cliente — user + site + publishable_keys ativas + quota + consumo.
 * Auth via cookie cliente_session.
 */
export function obterConfiguracoes(
  opts: ApiOptions,
): Promise<Result<ConfiguracoesOk, ConfiguracoesErrorCode>> {
  return getJson<ConfiguracoesOk, ConfiguracoesErrorCode>(
    `${opts.apiUrl}/cliente/auth/configuracoes`,
    opts.fetchImpl ?? fetch,
    { 401: 'NAO_AUTENTICADO', 404: 'SITE_NAO_ENCONTRADO', 500: 'BACKEND_INCOMPLETO' },
  );
}

/**
 * Lista arquivos arquivados disponiveis pra download (auth via cookie cliente_session).
 *
 * O backend retorna 401 se cookie ausente/invalido. 200 com `{arquivos: []}` se
 * R2 esta configurado mas nao tem nada do cliente atual ou se R2 nao esta
 * configurado (blueprint nao registrado vira 404 — tratado como INESPERADO).
 */
export function listarExports(
  opts: ApiOptions,
): Promise<Result<ListarExportsOk, ListarExportsErrorCode>> {
  return getJson<ListarExportsOk, ListarExportsErrorCode>(
    `${opts.apiUrl}/cliente/exportar`,
    opts.fetchImpl ?? fetch,
    { 401: 'NAO_AUTENTICADO' },
  );
}

const RE_DIA_ISO = /^\d{4}-\d{2}-\d{2}$/;

/**
 * URL absoluta pra GET /cliente/exportar/<dia> — backend retorna 302 com
 * signed URL R2 (TTL 5min). `<a href={url}>` deixa o browser seguir o redirect.
 */
export function urlDownloadExport(apiUrl: string, dia: string): string {
  if (!RE_DIA_ISO.test(dia)) {
    throw new Error(`dia invalido: ${dia} (esperado YYYY-MM-DD)`);
  }
  return `${apiUrl}/cliente/exportar/${dia}`;
}

/**
 * Constroi URL absoluta pro dashboard logado (subdominio app.X em prod).
 * Necessario porque, depois do cutover do apex pro CF Pages, redirect
 * relativo `/cliente/metricas` cai numa pagina estatica que nao existe.
 *
 * @param dashboardUrl base (ex: https://app.dsplayground.com.br/cliente/metricas)
 * @param query params opcionais (ex: { welcome: 'true' })
 */
export function urlDashboard(
  dashboardUrl: string,
  query?: Record<string, string>,
): string {
  if (!query || Object.keys(query).length === 0) return dashboardUrl;
  const sep = dashboardUrl.includes('?') ? '&' : '?';
  const qs = new URLSearchParams(query).toString();
  return `${dashboardUrl}${sep}${qs}`;
}
