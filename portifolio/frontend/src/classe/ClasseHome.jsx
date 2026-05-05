import { HeatmapUtils, WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';
import { DEBUG_ENABLED } from '../config.js';

// Controle global de página ativa para evitar coleta simultânea
window.__ACTIVE_PAGE_CONTROLLER__ = window.__ACTIVE_PAGE_CONTROLLER__ || null;
window.__ACTIVE_PAGE_TYPE__ = window.__ACTIVE_PAGE_TYPE__ || null;

export default class ClasseHome {
    constructor(root) {
        this.root = root;
        this.executando = false;
        this.pageType = '/';
        this.isPageVisible = true; // Controle de visibilidade

        // Definindo seletores específicos usando os IDs padronizados
        const seletoresInteresse = [
            '#home_header',
            '#home_content',
            '#home_footer',
            '#home_title',
            '.tech-btn',  // Mantém classes quando fizer sentido
            '#home_btn_grafana',
            '#home_btn_react',
            '#home_btn_redux',
            '#home_btn_reacticons',
            '#home_btn_vite'
        ].join(', ');

        this.heatmap = new HeatmapUtils(root, seletoresInteresse, this.pageType);

        // Mapeia elementos específicos para uso direto
        this.elementos = {
            header: root?.querySelector('#home_header'),
            content: root?.querySelector('#home_content'),
            footer: root?.querySelector('#home_footer'),
            techButtons: Array.from(root?.querySelectorAll('.tech-btn') || [])
        };

        // Controle para coleta temporal
        this.colecaoTemporalAtiva = false;

        // Listener para verificar visibilidade da página
        this.visibilityChangeHandler = () => {
            this.isPageVisible = !document.hidden;
            if (DEBUG_ENABLED) {
                console.log(`🔍 [ClasseHome] Visibilidade alterada: ${this.isPageVisible ? 'visível' : 'oculta'}`);
            }
        };
    }

    iniciar() {
        if (this.executando) return;
        
        // Verificar se há outra página ativa e pará-la
        if (window.__ACTIVE_PAGE_CONTROLLER__ && window.__ACTIVE_PAGE_CONTROLLER__ !== this) {
            try {
                window.__ACTIVE_PAGE_CONTROLLER__.parar();
            } catch (error) {
                if (DEBUG_ENABLED) {
                    console.warn('⚠️ [ClasseHome] Erro ao parar controlador anterior:', error);
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
                        console.log('📊 [ClasseHome] Dados temporais enviados:', {
                            timestamp: new Date().toISOString(),
                            tempoPermanciaSegundos: this.heatmap.getTempoPermanciaSegundos(),
                            totalVisualizacoes: dados.get_total_visualizacoes ? dados.get_total_visualizacoes() : 0
                        });
                    }
                } else if (DEBUG_ENABLED) {
                    console.log('⏸️ [ClasseHome] Dados temporais não enviados - página não visível ou não ativa');
                }
            },
            5000 // 5 segundos
        );

        // Iniciar coleta temporal
        this.heatmap.iniciarColecaoTempoReal();
        this.colecaoTemporalAtiva = true;

        // Iniciar o HeatmapUtils para rastrear interações
        this.heatmap.iniciar();

        // Conectar ao WebSocket se necessário
        WebSocketService.connect();
        
        if (DEBUG_ENABLED) {
            console.log('🚀 [ClasseHome] Iniciado como página ativa - apenas coleta temporal');
        }
    }

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
            console.log('[ClasseHome] Coleta parada e delta residual enviado');
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
                        console.log(`📊 [ClasseHome] Dados temporais enviados (${intervalMs}ms):`, {
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

    // Este método precisa ser corrigido - a função estava com escopo incorreto
    getWebSocketStatus() {
        // Chama diretamente o WebSocketService para obter o status
        return WebSocketService.getConnectionStatus();
    }

    // Método para uso em componentes React
    criarControles() {
        return {
            enviarDados: this.enviarDados.bind(this),
            iniciar: this.iniciar.bind(this),
            parar: this.parar.bind(this),
            getWebSocketStatus: this.getWebSocketStatus.bind(this),
            getTempoPermancia: this.getTempoPermancia.bind(this),
            setIntervaloColecaoTemporal: this.setIntervaloColecaoTemporal.bind(this)
        };
    }
}
