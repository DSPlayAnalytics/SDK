/**
 * Resolve um identificador estavel para o elemento na ordem:
 * data-analytics-id > id > aria-label > primeira classe > tagName.
 * O `data-analytics-id` e preferido porque e controlado explicitamente
 * pelo consumidor e nao quebra com refactor de CSS/HTML.
 */
export function obterElementoId(el: HTMLElement | null | undefined): string {
  if (!el) return 'desconhecido';

  if (typeof el.getAttribute === 'function') {
    const dataAttr = el.getAttribute('data-analytics-id');
    if (dataAttr) return dataAttr;
  }

  if (el.id) return el.id;

  if (typeof el.getAttribute === 'function') {
    const aria = el.getAttribute('aria-label');
    if (aria) return aria;
  }

  if (typeof el.className === 'string' && el.className.trim()) {
    return el.className.trim().split(/\s+/)[0];
  }

  if (el.tagName) return el.tagName.toLowerCase();

  return 'desconhecido';
}

export function obterElementoTipo(el: HTMLElement | null | undefined): string {
  if (!el || !el.tagName) return 'desconhecido';
  return el.tagName.toLowerCase();
}
