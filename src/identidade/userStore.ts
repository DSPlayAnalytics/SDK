/**
 * Schema 1.2 (v0.4): identidade do usuario / org persistente em localStorage,
 * com fallback memoria pra ambientes sem storage (SSR / quota cheia).
 *
 * Decisoes (ver roadmap SDK v0.4):
 *  - userId / groupId: persistem em localStorage; resetam via reset().
 *  - anonId: cookie-equivalente em localStorage; regenerado a cada reset()
 *    pra atender LGPD "esqueca-me" sem cookie infraestrutura.
 *  - traits: NAO persistem — viajam so no envelope do __identify event.
 *    SDK nao retem PII no storage do navegador.
 *  - PII guard: regex log-only em debug; SDK nao bloqueia (cliente assina
 *    termos LGPD; bloqueio paternalista atrapalha adocao).
 */
import { v4 as uuidv4 } from 'uuid';

const KEY_USER = 'analytics_sdk.user_id';
const KEY_GROUP = 'analytics_sdk.group_id';
const KEY_ANON = 'analytics_sdk.anon_id';

// Heuristica conservadora — match-and-warn, nunca redigir/bloquear.
// Conjuntos foram testados em valores comuns; falsos positivos preferidos
// a falsos negativos pra incentivar revisao do dev.
const REGEX_PII: Record<string, RegExp> = {
  email: /[\w.+%-]+@[\w.-]+\.[a-z]{2,}/i,
  cpf: /\d{3}\.?\d{3}\.?\d{3}-?\d{2}/,
  phone: /\+?\d{2}\s?\d?\d?\s?\d{4,5}-?\d{4}/,
};

/**
 * Storage abstrato. localStorage real implementa esta interface; memoria
 * fornece a mesma forma pra SSR / fallback.
 */
interface Storage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/**
 * Storage que swallows excecoes do localStorage (storage cheio, modo
 * privado de Safari). Mantem o ultimo valor em memoria pra preservar
 * sessao mesmo quando persistencia falha.
 */
class StorageResiliente implements Storage {
  private cache = new Map<string, string>();

  getItem(key: string): string | null {
    if (this.cache.has(key)) return this.cache.get(key) ?? null;
    try {
      if (typeof localStorage !== 'undefined') {
        const v = localStorage.getItem(key);
        if (v !== null) this.cache.set(key, v);
        return v;
      }
    } catch {
      /* storage indisponivel — usa cache so */
    }
    return null;
  }

  setItem(key: string, value: string): void {
    this.cache.set(key, value);
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(key, value);
      }
    } catch {
      /* quota cheia / storage off — cache mantem em memoria */
    }
  }

  removeItem(key: string): void {
    this.cache.delete(key);
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(key);
      }
    } catch {
      /* idem */
    }
  }
}

class StorageMemoria implements Storage {
  private mapa = new Map<string, string>();

  getItem(key: string): string | null {
    return this.mapa.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.mapa.set(key, value);
  }

  removeItem(key: string): void {
    this.mapa.delete(key);
  }
}

export class UserStore {
  private storage: Storage;

  constructor(storage?: Storage) {
    this.storage = storage ?? new StorageResiliente();
  }

  getAnonId(): string {
    let id = this.storage.getItem(KEY_ANON);
    if (!id) {
      id = uuidv4();
      this.storage.setItem(KEY_ANON, id);
    }
    return id;
  }

  getUserId(): string | null {
    return this.storage.getItem(KEY_USER);
  }

  setUserId(id: unknown): void {
    if (typeof id !== 'string') return;
    const limpo = id.trim();
    if (!limpo) return;
    this.storage.setItem(KEY_USER, limpo);
  }

  getGroupId(): string | null {
    return this.storage.getItem(KEY_GROUP);
  }

  setGroupId(id: unknown): void {
    if (typeof id !== 'string') return;
    const limpo = id.trim();
    if (!limpo) return;
    this.storage.setItem(KEY_GROUP, limpo);
  }

  /**
   * Logout: apaga userId/groupId, regenera anonId. Atende cenario "esquecer
   * tudo" do user (logout, troca de dispositivo, LGPD direito ao esquecimento).
   * Eventos pos-reset usam novo anonId — nao linkam com sessao anterior.
   */
  reset(): void {
    this.storage.removeItem(KEY_USER);
    this.storage.removeItem(KEY_GROUP);
    this.storage.removeItem(KEY_ANON);
    // Pre-popula o anonId novo pra getAnonId() proximo retornar consistente.
    const novo = uuidv4();
    this.storage.setItem(KEY_ANON, novo);
  }

  /**
   * Heuristica de PII em traits. Retorna lista de chaves cujo valor parece
   * email/cpf/telefone. Caller decide o que fazer (geralmente: console.warn
   * em modo debug).
   *
   * Por que nao bloquear: cliente pode legitimamente mandar email hasheado,
   * CPF mascarado, etc. Falso positivo bloqueante quebra mais casos de uso
   * do que protege. Em LGPD, cliente assume responsabilidade por consentimento.
   */
  detectarPII(traits: Record<string, unknown> | undefined | null): string[] {
    if (!traits || typeof traits !== 'object') return [];
    const suspeitas: string[] = [];
    for (const [chave, valor] of Object.entries(traits)) {
      if (typeof valor !== 'string') continue;
      for (const regex of Object.values(REGEX_PII)) {
        if (regex.test(valor)) {
          suspeitas.push(chave);
          break;
        }
      }
    }
    return suspeitas;
  }
}

/**
 * Variante explicitamente em memoria — pra SSR ou testes que nao querem
 * tocar localStorage real.
 */
export function criarUserStoreMemoria(): UserStore {
  return new UserStore(new StorageMemoria());
}

// Singleton padrao usado pelo SDK em runtime. Consumidores avancados podem
// instanciar UserStore manualmente pra controlar storage.
export const userStore = new UserStore();
