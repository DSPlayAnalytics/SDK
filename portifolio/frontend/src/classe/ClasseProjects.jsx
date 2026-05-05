import { HeatmapUtils, WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';
import { DEBUG_ENABLED } from '../config.js';

// Usar o mesmo controle global das outras classes
export default class ClasseProjects {
    constructor(root) {
        this.root = root;
        this.executando = false;
        this.pageType = '/projects';
        this.isPageVisible = true; // Controle de visibilidade

        // Definindo seletores específicos para Projects
        const seletoresInteresse = [
            '#projects_header',
            '#projects_content',
            '#projects_footer',
            '.project-item',
            '.card-actions button'
        ].join(', ');

        this.heatmap = new HeatmapUtils(root, seletoresInteresse, this.pageType);

        // Controle para coleta temporal
        this.colecaoTemporalAtiva = false;

        // Listener para verificar visibilidade da página
        this.visibilityChangeHandler = () => {
            this.isPageVisible = !document.hidden;
            if (DEBUG_ENABLED) {
                console.log(`🔍 [ClasseProjects] Visibilidade alterada: ${this.isPageVisible ? 'visível' : 'oculta'}`);
            }
        };
    }

    // Renomeando para padronizar com a chamada feita no SlidesCarousel.jsx
    start() {
        return this.iniciar();
    }

    stop() {
        return this.parar();
    }

    // Método original
    iniciar() {
        if (this.executando) return;
        
        // Verificar se há outra página ativa e pará-la
        if (window.__ACTIVE_PAGE_CONTROLLER__ && window.__ACTIVE_PAGE_CONTROLLER__ !== this) {
            try {
                window.__ACTIVE_PAGE_CONTROLLER__.parar();
            } catch (error) {
                if (DEBUG_ENABLED) {
                    console.warn('⚠️ [ClasseProjects] Erro ao parar controlador anterior:', error);
                }
            }
        }
        
        // Definir como página ativa
        window.__ACTIVE_PAGE_CONTROLLER__ = this;
        window.__ACTIVE_PAGE_TYPE__ = this.pageType;
        
        this.executando = true;
        
        // Adicionar listener de visibilidade
        document.addEventListener('visibilitychange', this.visibilityChangeHandler);

        // Configurar coleta temporal em tempo real (5 segundos)
        this.heatmap.configurarColecaoTempoReal(
            (dados) => {
                // Só enviar se página estiver visível e for a página ativa
                if (this.isPageVisible && window.__ACTIVE_PAGE_CONTROLLER__ === this) {
                    WebSocketService.sendAnalyticsDataImmediate(dados, false);
                    
                    if (DEBUG_ENABLED) {
                        console.log('📊 [ClasseProjects] Dados temporais enviados:', {
                            timestamp: new Date().toISOString(),
                            tempoPermanciaSegundos: this.heatmap.getTempoPermanciaSegundos(),
                            totalVisualizacoes: dados.get_total_visualizacoes ? dados.get_total_visualizacoes() : 0
                        });
                    }
                } else if (DEBUG_ENABLED) {
                    console.log('⏸️ [ClasseProjects] Dados temporais não enviados - página não visível ou não ativa');
                }
            },
            5000 // 5 segundos
        );

        // Iniciar coleta temporal
        this.heatmap.iniciarColecaoTempoReal();
        this.colecaoTemporalAtiva = true;

        this.heatmap.iniciar();
        WebSocketService.connect();
        
        if (DEBUG_ENABLED) {
            console.log('🚀 [ClasseProjects] Iniciado como página ativa - apenas coleta temporal');
        }
    }

    // Método original
    parar() {
        if (!this.executando) return;
        this.executando = false;
        
        // Limpar controle global se for a página ativa
        if (window.__ACTIVE_PAGE_CONTROLLER__ === this) {
            window.__ACTIVE_PAGE_CONTROLLER__ = null;
            window.__ACTIVE_PAGE_TYPE__ = null;
        }
        
        // Remover listener de visibilidade
        document.removeEventListener('visibilitychange', this.visibilityChangeHandler);

        // Parar coleta temporal
        this.colecaoTemporalAtiva = false;

        // heatmap.parar() emite o delta residual via callback antes de liberar timers
        this.heatmap.parar();

        if (DEBUG_ENABLED) {
            console.log('[ClasseProjects] Coleta parada e delta residual enviado');
        }
    }

    enviarDados() {
        if (!this.heatmap) return false;
        this.heatmap.emitirDeltaAgora();
        return true;
    }

    // Novo método para obter tempo de permanência
    getTempoPermancia() {
        if (this.heatmap) {
            return this.heatmap.getTempoPermanciaSegundos();
        }
        return 0;
    }

    // Novo método para configurar intervalo de coleta temporal
    setIntervaloColecaoTemporal(intervalMs) {
        if (this.heatmap && this.colecaoTemporalAtiva) {
            // Reconfigurar coleta temporal
            this.heatmap.configurarColecaoTempoReal(
                (dados) => {
                    WebSocketService.sendAnalyticsDataImmediate(dados, false);
                    
                    if (DEBUG_ENABLED) {
                        console.log(`📊 [ClasseProjects] Dados temporais enviados (${intervalMs}ms):`, {
                            timestamp: new Date().toISOString(),
                            tempoPermanciaSegundos: this.heatmap.getTempoPermanciaSegundos()
                        });
                    }
                },
                intervalMs
            );
            
            // Reiniciar coleta temporal com novo intervalo
            this.heatmap.iniciarColecaoTempoReal();
        }
    }

    getWebSocketStatus() {
        return WebSocketService.getConnectionStatus();
    }

    criarControles() {
        return {
            enviarDados: this.enviarDados.bind(this),
            iniciar: this.iniciar.bind(this),
            parar: this.parar.bind(this),
            getWebSocketStatus: this.getWebSocketStatus.bind(this),
            getTempoPermancia: this.getTempoPermancia.bind(this),
            setIntervaloColecaoTemporal: this.setIntervaloColecaoTemporal.bind(this),
            // Adicionar aliases para compatibilidade
            start: this.iniciar.bind(this),
            stop: this.parar.bind(this)
        };
    }

    // Propriedade para compatibilidade
    get running() {
        return this.executando;
    }
}
