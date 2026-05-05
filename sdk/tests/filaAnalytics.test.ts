import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { FilaAnalytics, StorageMemoria } from '../src/filaAnalytics.ts';
import type { StorageFila } from '../src/filaAnalytics.ts';
import type { HeatmapDados } from '../src';

const criarPayload = (marca: string): HeatmapDados => ({
  id_registro: marca,
  timestamp_inicial: 1000,
  timestamp_final: 2000,
  paginas: { [marca]: [] },
});

let storage: StorageFila;

beforeEach(() => {
  storage = new StorageMemoria();
});

afterEach(async () => {
  await storage.limpar();
});

describe('FilaAnalytics', () => {
  it('enfileira e conta itens', async () => {
    const fila = new FilaAnalytics(storage, 100);
    await fila.enfileirar(criarPayload('a'));
    await fila.enfileirar(criarPayload('b'));
    expect(await fila.tamanho()).toBe(2);
  });

  it('proximoLote retorna em ordem FIFO sem remover', async () => {
    const fila = new FilaAnalytics(storage, 100);
    const a = await fila.enfileirar(criarPayload('a'));
    const b = await fila.enfileirar(criarPayload('b'));
    await fila.enfileirar(criarPayload('c'));

    const lote = await fila.proximoLote(2);
    expect(lote.map((i) => i.id)).toEqual([a.id, b.id]);
    expect(await fila.tamanho()).toBe(3);
  });

  it('confirmar remove itens por id', async () => {
    const fila = new FilaAnalytics(storage, 100);
    const a = await fila.enfileirar(criarPayload('a'));
    const b = await fila.enfileirar(criarPayload('b'));

    await fila.confirmar([a.id]);
    expect(await fila.tamanho()).toBe(1);
    const restante = await fila.proximoLote(10);
    expect(restante[0].id).toBe(b.id);
  });

  it('respeita limite descartando os mais antigos (FIFO)', async () => {
    const fila = new FilaAnalytics(storage, 3);
    await fila.enfileirar(criarPayload('a'));
    await fila.enfileirar(criarPayload('b'));
    const c = await fila.enfileirar(criarPayload('c'));
    const d = await fila.enfileirar(criarPayload('d'));
    const e = await fila.enfileirar(criarPayload('e'));

    expect(await fila.tamanho()).toBe(3);
    const ordem = (await fila.proximoLote(10)).map((i) => i.id);
    expect(ordem).toEqual([c.id, d.id, e.id]);
  });

  it('limpar esvazia a fila', async () => {
    const fila = new FilaAnalytics(storage, 100);
    await fila.enfileirar(criarPayload('a'));
    await fila.limpar();
    expect(await fila.tamanho()).toBe(0);
  });

  it('sobrevive a reload — nova instancia da fila sobre o mesmo storage ve os itens', async () => {
    const fila1 = new FilaAnalytics(storage, 100);
    const s1 = await fila1.enfileirar(criarPayload('sobrevivente-1'));
    const s2 = await fila1.enfileirar(criarPayload('sobrevivente-2'));

    // simula reload: nova FilaAnalytics apontando pro mesmo storage
    const fila2 = new FilaAnalytics(storage, 100);
    expect(await fila2.tamanho()).toBe(2);
    const ordem = (await fila2.proximoLote(10)).map((i) => i.id);
    expect(ordem).toEqual([s1.id, s2.id]);
  });

  it('cada item ganha id unico e timestamp', async () => {
    const fila = new FilaAnalytics(storage, 100);
    const a = await fila.enfileirar(criarPayload('a'));
    const b = await fila.enfileirar(criarPayload('b'));
    expect(a.id).not.toBe(b.id);
    expect(a.timestamp).toBeLessThanOrEqual(b.timestamp);
  });

  it('remove funcoes do payload antes de enfileirar (IndexedDB DataCloneError)', async () => {
    // HeatmapDados.from_dict anexa metodos (get_total_cliques, etc.).
    // IndexedDB rejeita funcoes via structured clone; fila precisa sanitizar.
    const payload = {
      id_registro: 'x',
      timestamp_inicial: 1000,
      timestamp_final: 2000,
      paginas: {},
      get_total_cliques: () => 42,
      get_total_tempo_segundos: function () { return 5; },
    } as unknown as HeatmapDados;

    const fila = new FilaAnalytics(storage, 10);
    const item = await fila.enfileirar(payload);

    // payload armazenado nao deve conter nenhuma funcao
    const funcoes = Object.values(item.payload).filter((v) => typeof v === 'function');
    expect(funcoes).toHaveLength(0);
    expect(item.payload.paginas).toEqual({});
  });

  it('sobrescreve id_registro do payload com o id do item da fila', async () => {
    // Contrato: cada batch enfileirado ganha um id_registro unico (== item.id),
    // independente do que o caller tenha colocado no payload. Isso evita que o
    // cache de idempotencia do backend (chaveado por site_id + id_registro)
    // descarte batches legitimos como duplicatas quando o SDK reusa um id global.
    const fila = new FilaAnalytics(storage, 10);
    const item = await fila.enfileirar(criarPayload('id-global-reusado'));

    expect(item.payload.id_registro).toBe(item.id);
    expect(item.payload.id_registro).not.toBe('id-global-reusado');
  });

  it('batches distintos recebem id_registro distintos mesmo com payload identico', async () => {
    // Regressao do bug em producao: HeatmapRegistryGlobal emite o mesmo id_registro
    // em todos os batches, e o backend rejeitava tudo alem do primeiro como
    // evento=duplicado. Agora cada enfileirar gera id_registro novo.
    const fila = new FilaAnalytics(storage, 10);
    const a = await fila.enfileirar(criarPayload('reusado'));
    const b = await fila.enfileirar(criarPayload('reusado'));
    const c = await fila.enfileirar(criarPayload('reusado'));

    const ids = [a, b, c].map((i) => i.payload.id_registro);
    expect(new Set(ids).size).toBe(3);
    expect(ids).toEqual([a.id, b.id, c.id]);
  });

  it('retry do mesmo item preserva id_registro (idempotencia no backend)', async () => {
    // O WebSocketService re-emite item.payload ate ack; o backend usa
    // (site_id, id_registro) como chave de dedup. Relendo o item do storage,
    // id_registro tem que estar estavel, senao o backend grava duas vezes.
    const fila = new FilaAnalytics(storage, 10);
    const original = await fila.enfileirar(criarPayload('a'));

    const primeiraLeitura = await fila.proximoLote(1);
    const segundaLeitura = await fila.proximoLote(1);

    expect(primeiraLeitura[0].payload.id_registro).toBe(original.id);
    expect(segundaLeitura[0].payload.id_registro).toBe(original.id);
    expect(primeiraLeitura[0].payload.id_registro).toBe(
      segundaLeitura[0].payload.id_registro,
    );
  });
});
