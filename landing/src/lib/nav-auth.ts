/**
 * Cliente-side: detecta sessao via fetch /cliente/auth/me e troca Nav items.
 *
 * Cookie `cliente_session` e' HttpOnly (nao acessivel a JS) — fonte de verdade
 * fica no backend. fetch com `credentials: 'include'` propaga o cookie pelo
 * eTLD+1 (Domain=dsplayground.com.br) e backend devolve 200/401.
 *
 * Pra evitar flash visual de items errados:
 * - Nav renderiza estado deslogado por default (caso comum: visitante).
 * - Apos fetch, se logado, troca atomic via classList/innerHTML.
 *
 * Testavel: fetcher injetavel; DOM ops em ids previsiveis.
 */
export interface UserResumo {
  user_id: string;
  site_id: string;
  email: string;
  papel: string;
}

export type FetcherMe = () => Promise<
  | { ok: true; user: UserResumo }
  | { ok: false; status: number }
>;

/** Cria um fetcher real apontando pra api.X/cliente/auth/me. */
export function criarFetcherMe(apiUrl: string, fetchImpl: typeof fetch = fetch): FetcherMe {
  return async () => {
    try {
      const r = await fetchImpl(`${apiUrl}/cliente/auth/me`, {
        method: 'GET',
        credentials: 'include',
      });
      if (!r.ok) return { ok: false, status: r.status };
      const user = (await r.json()) as UserResumo;
      return { ok: true, user };
    } catch {
      return { ok: false, status: 0 };
    }
  };
}

/**
 * Aplica estado logado/deslogado nos itens do Nav.
 *
 * Espera os seguintes elementos no DOM (ids):
 * - `nav-deslogado`: container com items de visitante (Entrar, Criar conta)
 * - `nav-logado`: container com items de logado (Painel, Configurações, Sair)
 *
 * Default: ambos `hidden`. Esta funcao tira o hidden do correto + esconde o outro.
 * (Sem hidden inicial, visitante via "Painel" piscar antes do JS rodar.)
 */
export async function aplicarEstadoLogado(
  fetcher: FetcherMe,
  doc: Document = document,
): Promise<{ logado: boolean }> {
  const deslogadoEl = doc.getElementById('nav-deslogado');
  const logadoEl = doc.getElementById('nav-logado');
  if (!deslogadoEl || !logadoEl) return { logado: false };

  const r = await fetcher();
  if (r.ok) {
    deslogadoEl.classList.add('hidden');
    logadoEl.classList.remove('hidden');
    return { logado: true };
  }
  // 401, falha de rede ou 500 — assume visitante. Visitante e' o estado
  // dominante (qualquer um pode ver landing); em duvida, mostra ele.
  logadoEl.classList.add('hidden');
  deslogadoEl.classList.remove('hidden');
  return { logado: false };
}
