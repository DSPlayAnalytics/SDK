/**
 * Resolve URL de pos-login considerando o query param `?next=`.
 *
 * Aceita apenas paths same-origin que comecam em `/cliente/` (ou raiz `/`)
 * — bloqueia open-redirect (`?next=https://evil.com/login` ou `?next=//evil`)
 * e bloqueia escapar do escopo cliente (`?next=/admin`).
 *
 * Retorna `next` validado ou `fallback` (DASHBOARD_URL externo, geralmente).
 */
export function resolverDestinoPosLogin(
  query: URLSearchParams,
  fallback: string,
): string {
  const next = query.get('next');
  if (!next) return fallback;

  // Bloqueia URLs absolutas, protocolo-relativas (//evil), e backslash-tricks
  // que browsers normalizam pra forward slash.
  if (
    next.startsWith('http://') ||
    next.startsWith('https://') ||
    next.startsWith('//') ||
    next.startsWith('\\\\') ||
    next.startsWith('/\\') ||
    next.includes('@')
  ) {
    return fallback;
  }

  // So aceita paths que comecam em /cliente/
  if (!next.startsWith('/cliente/')) return fallback;

  return next;
}
