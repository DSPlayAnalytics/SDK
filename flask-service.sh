#!/bin/bash
# Script para gerenciar o serviço Flask no OLS

BACKEND_DIR="/usr/local/lsws/portifolio/html/portifolio/backend"
SERVICE_NAME="portifolio-flask"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cd "$BACKEND_DIR"

case "$1" in
    start)
        log_info "Iniciando serviço Flask..."
        if [ -f "flask.pid" ] && ps -p $(cat flask.pid) > /dev/null; then
            log_error "Serviço já está rodando (PID: $(cat flask.pid))"
            exit 1
        fi
        
        source venv/bin/activate
        export FLASK_ENV=production
        
        # Iniciar com gunicorn se disponível
        if command -v gunicorn &> /dev/null; then
            nohup gunicorn --worker-class eventlet -w 4 --bind 127.0.0.1:5000 app:app > flask.log 2>&1 &
        else
            nohup python3 app.py > flask.log 2>&1 &
        fi
        
        echo $! > flask.pid
        sleep 2
        
        if ps -p $(cat flask.pid) > /dev/null; then
            log_success "Serviço iniciado (PID: $(cat flask.pid))"
        else
            log_error "Falha ao iniciar serviço"
            exit 1
        fi
        ;;
        
    stop)
        log_info "Parando serviço Flask..."
        if [ -f "flask.pid" ]; then
            PID=$(cat flask.pid)
            if ps -p $PID > /dev/null; then
                kill $PID
                sleep 2
                if ps -p $PID > /dev/null; then
                    kill -9 $PID
                fi
                rm flask.pid
                log_success "Serviço parado"
            else
                log_error "Processo não encontrado"
                rm flask.pid
            fi
        else
            log_error "Arquivo PID não encontrado"
        fi
        ;;
        
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
        
    status)
        if [ -f "flask.pid" ] && ps -p $(cat flask.pid) > /dev/null; then
            PID=$(cat flask.pid)
            log_success "Serviço rodando (PID: $PID)"
            echo "Memória: $(ps -p $PID -o rss= | awk '{print $1/1024 " MB"}')"
            echo "CPU: $(ps -p $PID -o %cpu= | awk '{print $1"%"}')"
        else
            log_error "Serviço não está rodando"
            exit 1
        fi
        ;;
        
    logs)
        if [ -f "flask.log" ]; then
            tail -f flask.log
        else
            log_error "Arquivo de log não encontrado"
        fi
        ;;
        
    test)
        log_info "Testando API..."
        if curl -s http://127.0.0.1:5000/api/ > /dev/null; then
            log_success "API respondendo"
            curl -s http://127.0.0.1:5000/api/health | python3 -m json.tool
        else
            log_error "API não está respondendo"
        fi
        ;;
        
    freeze)
        log_info "Gerando requirements completo..."
        source venv/bin/activate
        pip freeze > requirements-$(date +%Y%m%d).txt
        log_success "Arquivo gerado: requirements-$(date +%Y%m%d).txt"
        echo "Dependências instaladas: $(pip list | wc -l)"
        ;;
        
    *)
        echo "Uso: $0 {start|stop|restart|status|logs|test|freeze}"
        echo ""
        echo "Comandos:"
        echo "  start   - Iniciar o serviço Flask"
        echo "  stop    - Parar o serviço Flask"
        echo "  restart - Reiniciar o serviço Flask"
        echo "  status  - Ver status do serviço"
        echo "  logs    - Ver logs em tempo real"
        echo "  test    - Testar conectividade da API"
        echo "  freeze  - Gerar requirements completo"
        exit 1
        ;;
esac