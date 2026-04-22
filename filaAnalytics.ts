import { v4 as uuidv4 } from 'uuid';

import type { HeatmapDados } from './HeatmapUtils.tsx';

export type PrioridadeFila = 'alta' | 'normal' | 'baixa';

export interface ItemFila {
  id: string;
  timestamp: number;
  payload: HeatmapDados;
  tentativas: number;
  prioridade: PrioridadeFila;
  ultimoErro?: string;
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

/** Deriva prioridade do payload (page_exit = alta; mousemove/hover = baixa). */
export function derivarPrioridade(payload: HeatmapDados): PrioridadeFila {
  try {
    const paginas = (payload as unknown as { paginas?: Record<string, unknown[]> }).paginas;
    if (!paginas) return 'normal';
    for (const registros of Object.values(paginas)) {
      if (!Array.isArray(registros)) continue;
      for (const registro of registros) {
        const eventos = (registro as { eventos?: Array<{ tipo?: string }> })?.eventos ?? [];
        for (const ev of eventos) {
          if (ev?.tipo === 'page_exit') return 'alta';
        }
      }
    }
    return 'normal';
  } catch {
    return 'normal';
  }
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
    const item: ItemFila = {
      id: uuidv4(),
      timestamp: Date.now(),
      payload: payloadLimpo,
      tentativas: 0,
      prioridade: derivarPrioridade(payloadLimpo),
    };
    await this.storage.enfileirar(item);
    await this.aplicarLimite();
    return item;
  }

  async proximoLote(n: number, excluirIds: Set<string> = new Set()): Promise<ItemFila[]> {
    const todos = await this.storage.listar();
    const disponiveis = todos.filter((i) => !excluirIds.has(i.id));
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

  async incrementarTentativa(id: string, erro?: string): Promise<ItemFila | null> {
    const todos = await this.storage.listar();
    const alvo = todos.find((i) => i.id === id);
    if (!alvo) return null;
    const atualizado: ItemFila = {
      ...alvo,
      tentativas: alvo.tentativas + 1,
      ultimoErro: erro,
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
