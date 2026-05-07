import { v4 as uuidv4 } from 'uuid';

import type { HeatmapDados } from './HeatmapUtils.tsx';

export type PrioridadeFila = 'alta' | 'normal' | 'baixa';

/** Delays por tentativa (1ª, 2ª, 3ª, 4ª, 5ª+). Jitter de 0–500ms somado em cima. */
export const BACKOFF_RETRY_MS = [1_000, 2_000, 4_000, 8_000, 30_000] as const;

export interface ItemFila {
  id: string;
  timestamp: number;
  payload: HeatmapDados;
  tentativas: number;
  prioridade: PrioridadeFila;
  ultimoErro?: string;
  /** Timestamp (ms epoch) antes do qual o item nao deve ser drenado (backoff por tentativa). */
  proximaTentativaApos?: number;
}

export interface StorageFila {
  enfileirar(item: ItemFila): Promise<void>;
  listar(): Promise<ItemFila[]>;
  remover(ids: string[]): Promise<void>;
  atualizar(item: ItemFila): Promise<void>;
  limpar(): Promise<void>;
}

export class StorageMemoria implements StorageFila {
  private itens: ItemFila[] = [];

  async enfileirar(item: ItemFila): Promise<void> {
    this.itens.push(item);
  }

  async listar(): Promise<ItemFila[]> {
    return [...this.itens].sort((a, b) => a.timestamp - b.timestamp);
  }

  async remover(ids: string[]): Promise<void> {
    if (!ids.length) return;
    const set = new Set(ids);
    this.itens = this.itens.filter((i) => !set.has(i.id));
  }

  async atualizar(item: ItemFila): Promise<void> {
    const idx = this.itens.findIndex((i) => i.id === item.id);
    if (idx >= 0) this.itens[idx] = item;
  }

  async limpar(): Promise<void> {
    this.itens = [];
  }
}

export class StorageLocalStorage implements StorageFila {
  private chave = 'analytics_sdk.fila';

  private ler(): ItemFila[] {
    try {
      const raw = localStorage.getItem(this.chave);
      return raw ? (JSON.parse(raw) as ItemFila[]) : [];
    } catch {
      return [];
    }
  }

  private escrever(itens: ItemFila[]): void {
    try {
      localStorage.setItem(this.chave, JSON.stringify(itens));
    } catch {
      /* cheio ou indisponivel */
    }
  }

  async enfileirar(item: ItemFila): Promise<void> {
    const itens = this.ler();
    itens.push(item);
    this.escrever(itens);
  }

  async listar(): Promise<ItemFila[]> {
    return this.ler().sort((a, b) => a.timestamp - b.timestamp);
  }

  async remover(ids: string[]): Promise<void> {
    if (!ids.length) return;
    const set = new Set(ids);
    this.escrever(this.ler().filter((i) => !set.has(i.id)));
  }

  async atualizar(item: ItemFila): Promise<void> {
    const itens = this.ler();
    const idx = itens.findIndex((i) => i.id === item.id);
    if (idx >= 0) {
      itens[idx] = item;
      this.escrever(itens);
    }
  }

  async limpar(): Promise<void> {
    try {
      localStorage.removeItem(this.chave);
    } catch {
      /* noop */
    }
  }
}

export class StorageIndexedDB implements StorageFila {
  private dbName = 'analytics_sdk';
  private storeName = 'fila';
  private versao = 1;
  private dbPromise: Promise<IDBDatabase> | null = null;

  private abrir(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;
    this.dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open(this.dbName, this.versao);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(this.storeName)) {
          db.createObjectStore(this.storeName, { keyPath: 'id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return this.dbPromise;
  }

  async enfileirar(item: ItemFila): Promise<void> {
    const db = await this.abrir();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readwrite');
      tx.objectStore(this.storeName).add(item);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async listar(): Promise<ItemFila[]> {
    const db = await this.abrir();
    return new Promise<ItemFila[]>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readonly');
      const req = tx.objectStore(this.storeName).getAll();
      req.onsuccess = () => {
        const itens = (req.result || []) as ItemFila[];
        resolve(itens.sort((a, b) => a.timestamp - b.timestamp));
      };
      req.onerror = () => reject(req.error);
    });
  }

  async remover(ids: string[]): Promise<void> {
    if (!ids.length) return;
    const db = await this.abrir();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readwrite');
      const store = tx.objectStore(this.storeName);
      ids.forEach((id) => store.delete(id));
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async atualizar(item: ItemFila): Promise<void> {
    const db = await this.abrir();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readwrite');
      tx.objectStore(this.storeName).put(item);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async limpar(): Promise<void> {
    const db = await this.abrir();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(this.storeName, 'readwrite');
      tx.objectStore(this.storeName).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
}

export function criarStorageFila(): StorageFila {
  if (typeof indexedDB !== 'undefined') {
    try {
      return new StorageIndexedDB();
    } catch {
      /* fall through */
    }
  }
  if (typeof localStorage !== 'undefined') {
    try {
      return new StorageLocalStorage();
    } catch {
      /* fall through */
    }
  }
  return new StorageMemoria();
}

const EVENTO_QUEUE_OVERFLOW = 'analytics:queue_overflow';
const EVENTO_ITEM_DEAD_LETTER = 'analytics:item_dead_lettered';
const EVENTO_PAYLOAD_REJECTED = 'analytics:payload_rejected';
const EVENTO_ENQUEUE_FAILED = 'analytics:enqueue_failed';

export function emitirEventoOverflow(detalhe: {
  droppedCount: number;
  oldestDroppedAt: number | null;
  reason: string;
}): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVENTO_QUEUE_OVERFLOW, { detail: detalhe }));
}

export function emitirEventoDeadLetter(detalhe: {
  idRegistro: string | null;
  tentativas: number;
  ultimoErro?: string;
}): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVENTO_ITEM_DEAD_LETTER, { detail: detalhe }));
}

export function emitirEventoPayloadRejected(detalhe: {
  idRegistro: string | null;
  code: string;
  fields: string[];
}): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVENTO_PAYLOAD_REJECTED, { detail: detalhe }));
}

export function emitirEventoEnqueueFailed(detalhe: {
  idRegistro: string | null;
  reason: string;
  storage: string;
}): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVENTO_ENQUEUE_FAILED, { detail: detalhe }));
}

/** Ordem de descarte: mais descartavel primeiro. Menor = descarta antes. */
const ORDEM_DESCARTE_POR_PRIORIDADE: Record<PrioridadeFila, number> = {
  baixa: 0,
  normal: 1,
  alta: 2,
};

// Onda 2: ordem de descarte (menor = descarta antes).
// mouse_move/hover = ruido de alto volume → baixa
// scroll_depth/touch = util mas abundante → normal
// click/element_exposure/page_view/page_exit/web_vital/custom → alta (nunca descartado)
const PRIORIDADE_POR_TIPO: Record<string, PrioridadeFila> = {
  mouse_move: 'baixa',
  hover: 'baixa',
  scroll_depth: 'normal',
  touch: 'normal',
};

/** Deriva prioridade do payload inspecionando tipos de evento.
 * Qualquer evento de alta prioridade (click, page_view, page_exit…) eleva o lote inteiro. */
export function derivarPrioridade(payload: HeatmapDados): PrioridadeFila {
  let melhor: PrioridadeFila = 'baixa';
  try {
    const paginas = (payload as unknown as { paginas?: Record<string, unknown[]> }).paginas;
    if (!paginas) return 'normal';
    for (const registros of Object.values(paginas)) {
      if (!Array.isArray(registros)) continue;
      for (const registro of registros) {
        const eventos = (registro as { eventos?: Array<{ tipo?: string }> })?.eventos ?? [];
        for (const ev of eventos) {
          const p = PRIORIDADE_POR_TIPO[ev?.tipo ?? ''] ?? 'alta';
          if (p === 'alta') return 'alta';
          if (p === 'normal' && melhor === 'baixa') melhor = 'normal';
        }
      }
    }
  } catch {
    return 'normal';
  }
  return melhor;
}

/** Remove funcoes e outros nao-serializaveis. IndexedDB recusa via structured clone
 * qualquer valor que contenha funcao (ex.: metodos anexados em HeatmapDados.from_dict).
 * JSON round-trip descarta funcoes silenciosamente e preserva os campos de dados. */
function sanitizarPayload(payload: HeatmapDados): HeatmapDados {
  return JSON.parse(JSON.stringify(payload)) as HeatmapDados;
}

export class FilaAnalytics {
  constructor(private storage: StorageFila, private limite: number = 500) {}

  async enfileirar(payload: HeatmapDados): Promise<ItemFila> {
    const payloadLimpo = sanitizarPayload(payload);
    // id_registro segue o id do item da fila: cada batch novo ganha um id unico
    // (o cache de idempotencia do backend chaveia por (site_id, id_registro) com
    // TTL de 10min, entao reusar o mesmo valor entre batches derruba todos menos
    // o primeiro), enquanto retries do mesmo item preservam o id e a idempotencia.
    const id = uuidv4();
    const payloadComId: HeatmapDados = { ...payloadLimpo, id_registro: id };
    const item: ItemFila = {
      id,
      timestamp: Date.now(),
      payload: payloadComId,
      tentativas: 0,
      prioridade: derivarPrioridade(payloadComId),
    };
    await this.storage.enfileirar(item);
    await this.aplicarLimite();
    return item;
  }

  async proximoLote(n: number, excluirIds: Set<string> = new Set()): Promise<ItemFila[]> {
    const agora = Date.now();
    const todos = await this.storage.listar();
    const disponiveis = todos.filter(
      (i) =>
        !excluirIds.has(i.id) &&
        (i.proximaTentativaApos === undefined || i.proximaTentativaApos <= agora),
    );
    return disponiveis.slice(0, Math.max(0, n));
  }

  async confirmar(ids: string[]): Promise<void> {
    await this.storage.remover(ids);
  }

  async tamanho(): Promise<number> {
    return (await this.storage.listar()).length;
  }

  async limpar(): Promise<void> {
    await this.storage.limpar();
  }

  async incrementarTentativa(
    id: string,
    erro?: string,
    backoffMs: readonly number[] = BACKOFF_RETRY_MS,
  ): Promise<ItemFila | null> {
    const todos = await this.storage.listar();
    const alvo = todos.find((i) => i.id === id);
    if (!alvo) return null;
    const novasTentativas = alvo.tentativas + 1;
    const delayBase = backoffMs[Math.min(novasTentativas - 1, backoffMs.length - 1)];
    const jitter = Math.floor(Math.random() * 500);
    const atualizado: ItemFila = {
      ...alvo,
      tentativas: novasTentativas,
      ultimoErro: erro,
      proximaTentativaApos: Date.now() + delayBase + jitter,
    };
    await this.storage.atualizar(atualizado);
    return atualizado;
  }

  /** Remove itens mais antigos respeitando prioridade — baixa primeiro, alta nunca. */
  async descartarPorPrioridade(n: number): Promise<number> {
    if (n <= 0) return 0;
    const todos = await this.storage.listar();
    const ordenados = [...todos].sort((a, b) => {
      const pa = ORDEM_DESCARTE_POR_PRIORIDADE[a.prioridade];
      const pb = ORDEM_DESCARTE_POR_PRIORIDADE[b.prioridade];
      if (pa !== pb) return pa - pb;
      return a.timestamp - b.timestamp;
    });
    // Nao remove itens de prioridade alta, mesmo sob overflow.
    const candidatos = ordenados
      .filter((i) => i.prioridade !== 'alta')
      .slice(0, n);
    if (candidatos.length === 0) return 0;
    await this.storage.remover(candidatos.map((i) => i.id));
    emitirEventoOverflow({
      droppedCount: candidatos.length,
      oldestDroppedAt: candidatos[0]?.timestamp ?? null,
      reason: 'limit_exceeded',
    });
    return candidatos.length;
  }

  /** Descarta itens cujo timestamp e <= tsLimite (usado em resync pos-reconnect). */
  async descartarAteTimestamp(tsLimite: number): Promise<string[]> {
    const todos = await this.storage.listar();
    const alvos = todos.filter((i) => i.timestamp <= tsLimite).map((i) => i.id);
    if (alvos.length) {
      await this.storage.remover(alvos);
    }
    return alvos;
  }

  private async aplicarLimite(): Promise<void> {
    const todos = await this.storage.listar();
    if (todos.length <= this.limite) return;
    const excesso = todos.length - this.limite;
    await this.descartarPorPrioridade(excesso);
  }
}

// ---------------------------------------------------------------------------
// DeadLetterStore — Onda 2
// Persiste itens exauridos em localStorage com TTL 24h e limite de 100 entradas.
// ---------------------------------------------------------------------------

export interface ItemDeadLetter {
  idRegistro: string | null;
  tentativas: number;
  ultimoErro?: string;
  ts: number;
}

const DEAD_LETTER_KEY = 'analytics_sdk.dead_letter';
const DEAD_LETTER_MAX = 100;
const DEAD_LETTER_TTL_MS = 24 * 60 * 60 * 1000;

export class DeadLetterStore {
  private _memoria: ItemDeadLetter[] = [];

  private _lerStorage(): ItemDeadLetter[] {
    if (typeof localStorage === 'undefined') return this._memoria;
    try {
      const raw = localStorage.getItem(DEAD_LETTER_KEY);
      return raw ? (JSON.parse(raw) as ItemDeadLetter[]) : [];
    } catch {
      return [];
    }
  }

  private _escreverStorage(itens: ItemDeadLetter[]): void {
    if (typeof localStorage === 'undefined') {
      this._memoria = itens;
      return;
    }
    try {
      localStorage.setItem(DEAD_LETTER_KEY, JSON.stringify(itens));
    } catch {
      this._memoria = itens;
    }
  }

  adicionar(item: ItemDeadLetter): void {
    const agora = Date.now();
    const itens = this._lerStorage()
      .filter((i) => agora - i.ts < DEAD_LETTER_TTL_MS)  // purga expirados
      .concat(item)
      .slice(-DEAD_LETTER_MAX);                           // FIFO, mantém os mais recentes
    this._escreverStorage(itens);
  }

  ler(): ItemDeadLetter[] {
    const agora = Date.now();
    return this._lerStorage().filter((i) => agora - i.ts < DEAD_LETTER_TTL_MS);
  }

  limpar(): void {
    this._escreverStorage([]);
  }
}
