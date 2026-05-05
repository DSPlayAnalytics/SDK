import { describe, expect, it } from 'vitest';

import { obterElementoId, obterElementoTipo } from '../src/util/obterElementoId.ts';
import { detectarDispositivo } from '../src/util/detectarDispositivo.ts';

describe('obterElementoId', () => {
  it('prioriza data-analytics-id', () => {
    const el = document.createElement('button');
    el.id = 'btn-x';
    el.setAttribute('aria-label', 'Botao');
    el.setAttribute('data-analytics-id', 'cta-principal');
    el.className = 'primary-btn destaque';
    expect(obterElementoId(el)).toBe('cta-principal');
  });

  it('cai para id quando nao tem data-analytics-id', () => {
    const el = document.createElement('button');
    el.id = 'btn-x';
    el.setAttribute('aria-label', 'Botao');
    expect(obterElementoId(el)).toBe('btn-x');
  });

  it('cai para aria-label quando nao tem id', () => {
    const el = document.createElement('button');
    el.setAttribute('aria-label', 'Enviar');
    el.className = 'enviar-btn';
    expect(obterElementoId(el)).toBe('Enviar');
  });

  it('cai para primeira classe quando nao tem aria-label', () => {
    const el = document.createElement('div');
    el.className = 'card destaque';
    expect(obterElementoId(el)).toBe('card');
  });

  it('cai para tagName quando nada mais esta disponivel', () => {
    const el = document.createElement('section');
    expect(obterElementoId(el)).toBe('section');
  });

  it('retorna desconhecido quando o elemento e nulo', () => {
    expect(obterElementoId(null)).toBe('desconhecido');
    expect(obterElementoId(undefined)).toBe('desconhecido');
  });
});

describe('obterElementoTipo', () => {
  it('retorna a tag em minusculo', () => {
    const el = document.createElement('BUTTON');
    expect(obterElementoTipo(el)).toBe('button');
  });

  it('retorna desconhecido quando o elemento e nulo', () => {
    expect(obterElementoTipo(null)).toBe('desconhecido');
  });
});

describe('detectarDispositivo', () => {
  it('detecta mobile por user-agent iPhone', () => {
    expect(detectarDispositivo('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')).toBe('mobile');
  });

  it('detecta tablet por user-agent iPad', () => {
    expect(detectarDispositivo('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)')).toBe('tablet');
  });

  it('default desktop', () => {
    expect(detectarDispositivo('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('desktop');
  });
});
