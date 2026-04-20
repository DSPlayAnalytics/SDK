import { v4 as uuidv4 } from 'uuid';

import type { HeatmapDados } from './HeatmapUtils.tsx';

export interface ItemFila {
  id: string;
  timestamp: number;
  payload: HeatmapDados;
}

export interface StorageFila {
  enfileirar(item: ItemFila): Promise<void>;
  listar(): Promise<ItemFila[]>;
  remover(ids: string[]): Promise<void>;
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
      // localStorage cheio ou indisponivel — ignora (fila degrada em memoria)
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

  async limpar(): Promise<void> {
    try {
      localStorage.removeItem(this.chave);
    } catch {
      // noop
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
      // fall through
    }
  }
  if (typeof localStorage !== 'undefined') {
    try {
      return new StorageLocalStorage();
    } catch {
      // fall through
    }
  }
  return new StorageMemoria();
}

export class FilaAnalytics {
  constructor(private storage: StorageFila, private limite: number = 500) {}

  async enfileirar(payload: HeatmapDados): Promise<ItemFila> {
    const item: ItemFila = {
      id: uuidv4(),
      timestamp: Date.now(),
      payload,
    };
    await this.storage.enfileirar(item);
    await this.aplicarLimite();
    return item;
  }

  async proximoLote(n: number): Promise<ItemFila[]> {
    const todos = await this.storage.listar();
    return todos.slice(0, Math.max(0, n));
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

  private async aplicarLimite(): Promise<void> {
    const todos = await this.storage.listar();
    if (todos.length <= this.limite) return;
    const excesso = todos.length - this.limite;
    const idsRemovidos = todos.slice(0, excesso).map((i) => i.id);
    await this.storage.remover(idsRemovidos);
  }
}
