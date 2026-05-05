import { v4 as uuidv4 } from 'uuid';

import type { EventoNormalizado, MarcoScroll } from './tipos.ts';
import { normalizarClique } from './normalizadores/normalizarClique.ts';
import { normalizarToque } from './normalizadores/normalizarToque.ts';
import { normalizarScroll } from './normalizadores/normalizarScroll.ts';
import { normalizarMouseMove } from './normalizadores/normalizarMouseMove.ts';
import { normalizarHover } from './normalizadores/normalizarHover.ts';
import { normalizarExposicao } from './normalizadores/normalizarExposicao.ts';
import { normalizarPageView } from './normalizadores/normalizarPageView.ts';
import { normalizarPageExit } from './normalizadores/normalizarPageExit.ts';
import { obterElementoId, obterElementoTipo } from './util/obterElementoId.ts';

export type { EventoNormalizado, TipoEvento, MarcoScroll, MotivoSaida, NomeWebVital, RatingWebVital } from './tipos.ts';

export type MapaPaginasDados = { [pageId: string]: PaginaDados[] };

export interface PaginaDados {
    eventos: EventoNormalizado[];
    visualizacoes: number;
    segundos: number;
    timestamp_inicial: number | null;
    timestamp_final: number | null;
}

export interface HeatmapDados {
    id_registro: string;
    timestamp_inicial: number | null;
    timestamp_final: number | null;
    paginas: MapaPaginasDados;

    get_total_visualizacoes?: () => number;
    get_total_cliques?: () => number;
    get_total_tempo_segundos?: () => number;
    get_duracao_sessao_segundos?: () => number | null;
}

export namespace HeatmapDados {
    export function from_dict(data: any): HeatmapDados {
        const paginas: MapaPaginasDados = data.paginas || {};

        const result: HeatmapDados = {
            id_registro: data.id_registro || uuidv4(),
            timestamp_inicial: data.timestamp_inicial || null,
            timestamp_final: data.timestamp_final || null,
            paginas,
        };

        result.get_total_visualizacoes = function () {
            let total = 0;
            for (const sessoes of Object.values(result.paginas)) {
                if (sessoes instanceof Array) {
                    for (const sessao of sessoes) {
                        total += sessao.visualizacoes ?? 0;
                    }
                }
            }
            return total;
        };

        result.get_total_cliques = function () {
            let total = 0;
            for (const sessoes of Object.values(result.paginas)) {
                if (sessoes instanceof Array) {
                    for (const sessao of sessoes) {
                        const eventos = sessao.eventos ?? [];
                        for (const evento of eventos) {
                            if (evento.tipo === 'click') total += 1;
                        }
                    }
                }
            }
            return total;
        };

        result.get_total_tempo_segundos = function () {
            let total = 0;
            for (const sessoes of Object.values(result.paginas)) {
                if (sessoes instanceof Array) {
                    for (const sessao of sessoes) {
                        total += sessao.segundos ?? 0;
                    }
                }
            }
            return total;
        };

        result.get_duracao_sessao_segundos = function () {
            if (!result.timestamp_inicial || !result.timestamp_final) return null;
            return (result.timestamp_final - result.timestamp_inicial) / 1000;
        };

        return result;
    }
}

function obterPageIdPadrao(): string {
    if (typeof window === 'undefined') return '/';
    return window.location.pathname || '/';
}

class HeatmapRegistryGlobal {
    private static instance: HeatmapRegistryGlobal;
    private _id_registro: string;
    private _timestamp_inicial: number | null = null;
    private _timestamp_final: number | null = null;
    private _paginas: MapaPaginasDados = {};

    private constructor() {
        this._id_registro = uuidv4();
    }

    public static getInstance(): HeatmapRegistryGlobal {
        if (!HeatmapRegistryGlobal.instance) {
            HeatmapRegistryGlobal.instance = new HeatmapRegistryGlobal();
        }
        return HeatmapRegistryGlobal.instance;
    }

    public getIdRegistro(): string {
        return this._id_registro;
    }

    public setTimestampInicial(timestamp: number): void {
        if (this._timestamp_inicial === null) {
            this._timestamp_inicial = timestamp;
        }
    }

    public setTimestampFinal(timestamp: number): void {
        this._timestamp_final = timestamp;
    }

    public setPaginaDados(tipo: string, dados: PaginaDados): void {
        this._paginas[tipo] = [dados];
    }

    public resetarRegistro(): void {
        this._id_registro = uuidv4();
        this._timestamp_inicial = null;
        this._timestamp_final = null;
        this._paginas = {};
    }

    public getDados(): HeatmapDados {
        return HeatmapDados.from_dict({
            id_registro: this._id_registro,
            timestamp_inicial: this._timestamp_inicial,
            timestamp_final: this._timestamp_final,
            paginas: this._paginas,
        });
    }
}

interface EstadoCommitado {
    eventos: number;
    visualizacoes: number;
    tempoAcumuladoMs: number;
}

interface HoverAtivo {
    inicio: number;
    elementoTipo: string;
}

interface ExposicaoAtiva {
    inicio: number;
    acumulado: number;
    percentVisivelMax: number;
}

// Buffer global para empilhar eventos oriundos de fontes externas (webVitals, enviarEvento).
let bufferAtivo: HeatmapUtils | null = null;

// Eventos disparados antes de qualquer HeatmapUtils ativar (ex: LCP candidato
// inicial, enviarEvento('app_carregado') chamado na ordem de mount do React).
// Drenados no primeiro iniciar(); descartados na sequencia pra nao vazar entre
// sessoes. Cap de 100 preserva o early signal e evita memory leak se nenhum
// controller jamais ativar.
const PENDENTES_MAX = 100;
let eventosPendentes: EventoNormalizado[] = [];
let pendentesDrenados = false;

export class HeatmapUtils {
    root: HTMLElement;
    private _paginaTipo: string;
    private _visualizacoes: number;
    private _timestamp_inicial: number | null;
    private _timestamp_final: number | null;
    private _executando: boolean = false;

    private _eventos: EventoNormalizado[] = [];
    private _scrollMarcosAtingidos: Set<MarcoScroll> = new Set();
    private _scrollMaxPercent: number = 0;
    private _ultimoMouseMoveTs: number | null = null;
    private _hoverAtivos: { [id: string]: HoverAtivo } = {};
    private _exposicaoAtivos: { [id: string]: ExposicaoAtiva } = {};
    private _observer: IntersectionObserver | null = null;
    private hoverSelector: string | null;

    private _hoverListeners: Array<{ el: HTMLElement; id: string; enter: EventListener; leave: EventListener }> = [];

    private _registry: HeatmapRegistryGlobal;

    private _tempoRealTimer: ReturnType<typeof setInterval> | null = null;
    private _intervalColeta: number = 5000;
    private _taxaAmostragemMouseMove: number = 5;
    private _onTempoRealCallback: ((dados: HeatmapDados) => void) | null = null;
    private _ultimoTimestamp: number = Date.now();
    private _tempoAcumulado: number = 0;
    private _pageVisibilityListener: (() => void) | null = null;

    private _committed: EstadoCommitado;
    private _ultimoCommitTs: number | null = null;

    constructor(root: HTMLElement = document.body, hoverSelector: string | null = null, paginaTipo: string = obterPageIdPadrao()) {
        this.root = root;
        this._paginaTipo = paginaTipo;
        this._registry = HeatmapRegistryGlobal.getInstance();
        this._visualizacoes = 0;
        this._timestamp_inicial = null;
        this._timestamp_final = null;
        this.hoverSelector = hoverSelector;

        this._committed = { eventos: 0, visualizacoes: 0, tempoAcumuladoMs: 0 };

        this._onClick = this._onClick.bind(this);
        this._onScroll = this._onScroll.bind(this);
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onTouchMove = this._onTouchMove.bind(this);
        this._onIntersection = this._onIntersection.bind(this);

        console.log(`[HeatmapUtils] Construido para pagina ${paginaTipo}`, { id_registro: this._registry.getIdRegistro() });
    }

    iniciar() {
        if (this._executando) return;
        this._executando = true;

        // eslint-disable-next-line @typescript-eslint/no-this-alias
        bufferAtivo = this;

        this._visualizacoes += 1;
        this._timestamp_inicial = Date.now();
        this._registry.setTimestampInicial(this._timestamp_inicial);
        this._ultimoCommitTs = this._timestamp_inicial;

        this._ultimoTimestamp = Date.now();
        this._tempoAcumulado = 0;
        this._setupPageVisibilityListener();

        // Drena eventos enfileirados antes da primeira ativacao (web vitals
        // candidatos, enviarEvento chamado em ordem de mount). Atribui ao
        // page_type da primeira pagina ativa — pragmatico: na maioria dos apps
        // o primeiro mount ocorre na rota inicial onde os web vitals fazem sentido.
        if (!pendentesDrenados && eventosPendentes.length > 0) {
            for (const evt of eventosPendentes) this._eventos.push(evt);
            eventosPendentes = [];
            pendentesDrenados = true;
        }

        const eventoPageView = normalizarPageView({
            pageId: this._paginaTipo,
            path: this._paginaTipo,
            title: typeof document !== 'undefined' ? document.title : undefined,
        });
        if (eventoPageView) this._eventos.push(eventoPageView);

        this.root.addEventListener('click', this._onClick);
        this.root.addEventListener('scroll', this._onScroll, { passive: true });
        this.root.addEventListener('mousemove', this._onMouseMove);
        this.root.addEventListener('touchmove', this._onTouchMove, { passive: true });

        if (this.hoverSelector) {
            const elems = Array.from(this.root.querySelectorAll<HTMLElement>(this.hoverSelector));
            elems.forEach((el) => {
                const id = obterElementoId(el);
                const enter = () => this._iniciarHover(el, id);
                const leave = () => this._encerrarHover(id);
                el.addEventListener('mouseenter', enter);
                el.addEventListener('mouseleave', leave);
                this._hoverListeners.push({ el, id, enter, leave });
            });
        }

        this._observer = new IntersectionObserver(this._onIntersection, {
            threshold: [0, 0.25, 0.5, 0.75, 1],
            root: null,
            rootMargin: '0px',
        });

        const elementos = Array.from(
            this.root.querySelectorAll<HTMLElement>(
                'h1, h2, h3, h4, h5, p, button, a, img, .card-carousel, .skill-badge, .tech-btn, [data-analytics-id]',
            ),
        );
        elementos.forEach((el) => this._observer?.observe(el));
    }

    parar(motivo: 'navegacao' | 'unmount' | 'aba_fechada' = 'unmount') {
        if (!this._executando) return;
        this._executando = false;

        const now = Date.now();
        this._timestamp_final = now;
        this._registry.setTimestampFinal(now);

        this.root.removeEventListener('click', this._onClick);
        this.root.removeEventListener('scroll', this._onScroll);
        this.root.removeEventListener('mousemove', this._onMouseMove);
        this.root.removeEventListener('touchmove', this._onTouchMove);

        this._hoverListeners.forEach(({ el, enter, leave }) => {
            el.removeEventListener('mouseenter', enter);
            el.removeEventListener('mouseleave', leave);
        });
        this._hoverListeners = [];

        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }

        Object.keys(this._hoverAtivos).forEach((id) => this._encerrarHover(id));
        Object.keys(this._exposicaoAtivos).forEach((id) => {
            const estado = this._exposicaoAtivos[id];
            const duracao = estado.acumulado + (now - estado.inicio);
            delete this._exposicaoAtivos[id];
            if (duracao <= 0) return;
            const evento = normalizarExposicao({
                elementoId: id,
                duracao_ms: duracao,
                percent_visivel_max: estado.percentVisivelMax,
            });
            if (evento) this._eventos.push(evento);
        });

        this._atualizarTempoAcumulado();
        const duracaoPagina = this._timestamp_inicial != null ? now - this._timestamp_inicial : 0;
        const eventoExit = normalizarPageExit({
            pageId: this._paginaTipo,
            duracao_ms: Math.max(0, duracaoPagina),
            motivo,
        });
        if (eventoExit) this._eventos.push(eventoExit);

        this._registry.setPaginaDados(this._paginaTipo, this.getPaginaDadosCumulativo());
        this._emitirDelta();
        this._stopTempoRealCollection();

        if (bufferAtivo === this) bufferAtivo = null;
    }

    configurarColecaoTempoReal(callback: (dados: HeatmapDados) => void, intervalo: number = 5000, taxaAmostragemMouseMove?: number) {
        this._onTempoRealCallback = callback;
        this._intervalColeta = intervalo;
        if (typeof taxaAmostragemMouseMove === 'number' && taxaAmostragemMouseMove > 0) {
            this._taxaAmostragemMouseMove = taxaAmostragemMouseMove;
        }
        this._setupPageVisibilityListener();
    }

    iniciarColecaoTempoReal() {
        if (this._tempoRealTimer) clearInterval(this._tempoRealTimer);
        this._ultimoTimestamp = Date.now();
        this._tempoAcumulado = 0;

        this._tempoRealTimer = setInterval(() => {
            this._atualizarTempoAcumulado();
            this._emitirDelta();
        }, this._intervalColeta);
    }

    private _stopTempoRealCollection() {
        if (this._tempoRealTimer) {
            clearInterval(this._tempoRealTimer);
            this._tempoRealTimer = null;
        }
        if (this._pageVisibilityListener) {
            document.removeEventListener('visibilitychange', this._pageVisibilityListener);
            this._pageVisibilityListener = null;
        }
    }

    private _atualizarTempoAcumulado() {
        const agora = Date.now();
        if (!document.hidden) {
            this._tempoAcumulado += agora - this._ultimoTimestamp;
        }
        this._ultimoTimestamp = agora;
    }

    private _setupPageVisibilityListener() {
        if (this._pageVisibilityListener) {
            document.removeEventListener('visibilitychange', this._pageVisibilityListener);
        }
        this._pageVisibilityListener = () => {
            const agora = Date.now();
            if (document.hidden) {
                this._atualizarTempoAcumulado();
            } else {
                this._ultimoTimestamp = agora;
            }
        };
        document.addEventListener('visibilitychange', this._pageVisibilityListener);
    }

    getTempoPermanciaSegundos(): number {
        if (!this._executando) {
            return Math.floor(this._tempoAcumulado / 1000);
        }
        this._atualizarTempoAcumulado();
        return Math.floor(this._tempoAcumulado / 1000);
    }

    private _onClick(e: MouseEvent) {
        const evento = normalizarClique(e);
        if (evento) this._eventos.push(evento);
    }

    private _onTouchMove(e: TouchEvent) {
        const evento = normalizarToque(e);
        if (evento) this._eventos.push(evento);
    }

    private _onScroll() {
        const scrollMax = this.root.scrollHeight - this.root.clientHeight;
        const percent = scrollMax > 0 ? Math.round((this.root.scrollTop / scrollMax) * 100) : 0;
        if (percent > this._scrollMaxPercent) this._scrollMaxPercent = percent;

        const marcos: MarcoScroll[] = [25, 50, 75, 100];
        for (const marco of marcos) {
            if (percent >= marco && !this._scrollMarcosAtingidos.has(marco)) {
                this._scrollMarcosAtingidos.add(marco);
                const evento = normalizarScroll({ marco, maxPercent: this._scrollMaxPercent });
                if (evento) this._eventos.push(evento);
            }
        }
    }

    private _onMouseMove(e: MouseEvent) {
        const evento = normalizarMouseMove(e, {
            ultimoTimestamp: this._ultimoMouseMoveTs,
            taxaPorSegundo: this._taxaAmostragemMouseMove,
        });
        if (!evento) return;
        this._ultimoMouseMoveTs = evento.timestamp;
        this._eventos.push(evento);
    }

    private _iniciarHover(el: HTMLElement, id: string) {
        if (this._hoverAtivos[id]) return;
        this._hoverAtivos[id] = { inicio: Date.now(), elementoTipo: obterElementoTipo(el) };
    }

    private _encerrarHover(id: string) {
        const estado = this._hoverAtivos[id];
        if (!estado) return;
        const duracao = Date.now() - estado.inicio;
        delete this._hoverAtivos[id];
        const evento = normalizarHover({ elementoId: id, duracao_ms: duracao, elemento_tipo: estado.elementoTipo });
        if (evento) this._eventos.push(evento);
    }

    private _onIntersection(entries: IntersectionObserverEntry[]) {
        const now = Date.now();
        entries.forEach((entry) => {
            const el = entry.target as HTMLElement;
            const id = obterElementoId(el);
            const percent = Math.round((entry.intersectionRatio ?? 0) * 100);

            const estado = this._exposicaoAtivos[id];

            if (entry.isIntersecting) {
                if (!estado) {
                    this._exposicaoAtivos[id] = { inicio: now, acumulado: 0, percentVisivelMax: percent };
                } else {
                    if (percent > estado.percentVisivelMax) estado.percentVisivelMax = percent;
                }
            } else if (estado) {
                const duracao = estado.acumulado + (now - estado.inicio);
                const percentMax = Math.max(estado.percentVisivelMax, percent);
                delete this._exposicaoAtivos[id];
                const evento = normalizarExposicao({
                    elementoId: id,
                    duracao_ms: duracao,
                    percent_visivel_max: percentMax,
                });
                if (evento) this._eventos.push(evento);
            }
        });
    }

    /**
     * Empilha um evento ja normalizado vindo de uma fonte externa (webVitals, enviarEvento).
     * Respeita a pagina ativa — so aceita se o HeatmapUtils estiver em execucao.
     */
    empilharEventoExterno(evento: EventoNormalizado): boolean {
        if (!this._executando) return false;
        this._eventos.push(evento);
        return true;
    }

    static empilharEventoNoAtivo(evento: EventoNormalizado): boolean {
        if (!bufferAtivo) {
            // Sem pagina ativa: enfileira pra drenar no primeiro iniciar(). Cap em
            // PENDENTES_MAX descartando os mais novos — preserva o early signal
            // (LCP candidato, primeiro custom event) que e o motivo do buffer existir.
            if (eventosPendentes.length >= PENDENTES_MAX) return false;
            eventosPendentes.push(evento);
            return true;
        }
        return bufferAtivo.empilharEventoExterno(evento);
    }

    private getPaginaDadosCumulativo(): PaginaDados {
        return {
            eventos: [...this._eventos],
            visualizacoes: this._visualizacoes,
            segundos: this.getTempoPermanciaSegundos(),
            timestamp_inicial: this._timestamp_inicial,
            timestamp_final: this._timestamp_final,
        };
    }

    private getPaginaDadosDelta(): PaginaDados {
        const now = Date.now();
        this._atualizarTempoAcumulado();

        const segundosDelta = Math.max(
            0,
            Math.floor((this._tempoAcumulado - this._committed.tempoAcumuladoMs) / 1000),
        );

        const windowStart = this._ultimoCommitTs ?? this._timestamp_inicial ?? now;

        const delta: PaginaDados = {
            eventos: this._eventos.slice(this._committed.eventos),
            visualizacoes: this._visualizacoes - this._committed.visualizacoes,
            segundos: segundosDelta,
            timestamp_inicial: windowStart,
            timestamp_final: now,
        };

        this._committed = {
            eventos: this._eventos.length,
            visualizacoes: this._visualizacoes,
            tempoAcumuladoMs: this._tempoAcumulado,
        };
        this._ultimoCommitTs = now;

        return delta;
    }

    private _emitirDelta(): void {
        if (!this._onTempoRealCallback) return;
        const delta = this.getPaginaDadosDelta();
        const payload: HeatmapDados = {
            id_registro: this._registry.getIdRegistro(),
            timestamp_inicial: delta.timestamp_inicial,
            timestamp_final: delta.timestamp_final,
            paginas: { [this._paginaTipo]: [delta] },
        };
        this._onTempoRealCallback(HeatmapDados.from_dict(payload));
    }

    emitirDeltaAgora(): void {
        this._atualizarTempoAcumulado();
        this._emitirDelta();
    }

    getDados(): HeatmapDados {
        const now = Date.now();
        this._timestamp_final = now;
        this._registry.setTimestampFinal(now);
        this._registry.setPaginaDados(this._paginaTipo, this.getPaginaDadosCumulativo());
        return this._registry.getDados();
    }

    get running(): boolean {
        return this._executando;
    }

    get executando(): boolean {
        return this._executando;
    }

    start() {
        return this.iniciar();
    }

    stop() {
        return this.parar();
    }

    static getDadosGlobais(): HeatmapDados {
        return HeatmapRegistryGlobal.getInstance().getDados();
    }

    static resetarRegistro(): void {
        HeatmapRegistryGlobal.getInstance().resetarRegistro();
        bufferAtivo = null;
        eventosPendentes = [];
        pendentesDrenados = false;
    }
}
