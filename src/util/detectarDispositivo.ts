export type TipoDispositivo = 'mobile' | 'tablet' | 'desktop';

export function detectarDispositivo(userAgent?: string): TipoDispositivo {
  const fonte = userAgent ?? (typeof navigator !== 'undefined' ? navigator.userAgent : '');
  const ua = fonte.toLowerCase();

  if (/tablet|ipad/.test(ua)) return 'tablet';
  if (/mobile|android|iphone|ipod/.test(ua)) return 'mobile';
  return 'desktop';
}
