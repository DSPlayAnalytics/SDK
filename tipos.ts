export type TipoEvento =
  | 'page_view'
  | 'page_exit'
  | 'click'
  | 'touch'
  | 'scroll_depth'
  | 'mouse_move'
  | 'hover'
  | 'element_exposure'
  | 'web_vital'
  | 'custom';

export interface EventoNormalizado {
  tipo: TipoEvento;
  timestamp: number;
  dados: Record<string, unknown>;
}

export type MarcoScroll = 25 | 50 | 75 | 100;

export type MotivoSaida = 'navegacao' | 'unmount' | 'aba_fechada';

export type NomeWebVital = 'LCP' | 'CLS' | 'INP';

export type RatingWebVital = 'good' | 'needs-improvement' | 'poor';

export interface ContextoNormalizacao {
  now?: () => number;
}
