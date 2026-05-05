#!/bin/bash
# Script de deploy para produo OLS

set -e  # Parar em caso de erro

echo " Iniciando deploy para produo OLS..."

# Definir diretrios
BACKEND_DIR="/usr/local/lsws/portifolio/html/portifolio/backend"
PROJECT_ROOT="/usr/local/lsws/portifolio/html/portifolio"

# Funo para logs
log_info() {
    echo "[INFO] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

log_success() {
    echo "[SUCCESS] $1"
}

# Navegar para o diretrio do backend
log_info "Navegando para: $BACKEND_DIR"
cd "$BACKEND_DIR"

# Verificar se ambiente virtual existe
if [ ! -d "venv" ]; then
    log_error "Ambiente virtual no encontrado!"
    log_info "Execute primeiro: ./setup-env.sh"
    exit 1
fi

# Ativar ambiente virtual
log_info "Ativando ambiente virtual..."
source venv/bin/activate

# Verificar se est no ambiente virtual
if [[ "$VIRTUAL_ENV" == "" ]]; then
    log_error "Falha ao ativar ambiente virtual"
    exit 1
fi

log_success "Ambiente virtual ativo: $VIRTUAL_ENV"

# Carregar variveis de ambiente
if [ -f ".env" ]; then
    log_info "Carregando variveis de ambiente..."
    set -a  # Exportar automaticamente variveis
    source .env
    set +a
    log_success "Variveis carregadas"
else
    log_info "Arquivo .env no encontrado, usando configuraes padro..."
    export FLASK_ENV=production
    export INFLUXDB_MODE=local
fi

# Verificar e instalar dependncias se necessrio
log_info "Verificando dependncias..."
if ! pip show flask &> /dev/null; then
    log_info "Instalando dependncias..."
    pip install -r requirements.txt
fi

# Parar processo Flask anterior se existir
log_info "Verificando processos Flask anteriores..."
FLASK_PID=$(pgrep -f "python.*app.py" || true)
if [ ! -z "$FLASK_PID" ]; then
    log_info "Parando processo Flask anterior (PID: $FLASK_PID)..."
    kill $FLASK_PID
    sleep 2
    
    # Forar kill se necessrio
    if pgrep -f "python.*app.py" &> /dev/null; then
        log_info "Forando parada do processo..."
        pkill -9 -f "python.*app.py"
    fi
fi

# Testar configurao
log_info "Testando configurao Flask..."
if python3 -c "from app import app; print('Flask configurado corretamente')"; then
    log_success "Configurao Flask vlida"
else
    log_error "Erro na configurao Flask"
    exit 1
fi

# Limpar logs antigos
if [ -f "flask.log" ]; then
    mv flask.log "flask-$(date +%Y%m%d-%H%M%S).log"
fi

# Iniciar servidor Flask
log_info "Iniciando servidor Flask..."

# Usar gunicorn para produo se disponvel
if command -v gunicorn &> /dev/null; then
    log_info "Usando Gunicorn para produo..."
    nohup gunicorn --worker-class eventlet -w 4 --bind 127.0.0.1:5000 --timeout 60 --keep-alive 2 --max-requests 1000 app:app > flask.log 2>&1 &
    FLASK_PID=$!
else
    log_info "Usando servidor Flask de desenvolvimento..."
    nohup python3 app.py > flask.log 2>&1 &
    FLASK_PID=$!
fi

# Aguardar inicializao
sleep 3

# Verificar se processo est rodando
if ps -p $FLASK_PID > /dev/null; then
    log_success "Servidor Flask iniciado (PID: $FLASK_PID)"
    echo $FLASK_PID > flask.pid
else
    log_error "Falha ao iniciar servidor Flask"
    log_error "ltimas linhas do log:"
    tail -10 flask.log
    exit 1
fi

# Testar conectividade
log_info "Testando conectividade..."
sleep 2

if curl -s http://127.0.0.1:5000/api/ > /dev/null; then
    log_success "API respondendo corretamente"
else
    log_error "API no est respondendo"
    log_error "Verificar logs: tail -f flask.log"
fi

echo ""
log_success "Deploy concludo com sucesso!"
echo ""
echo " Informaes do deploy:"
echo "   PID do processo: $FLASK_PID"
echo "   Logs: tail -f $BACKEND_DIR/flask.log"
echo "   Parar servidor: kill $FLASK_PID"
echo ""
echo " URLs de teste:"
echo "   API Local: http://127.0.0.1:5000/api/"
echo "   API Produo: http://localhost:5000/api/"
echo "   Health Check: http://localhost:5000/api/health"
echo "   WebSocket: http://localhost:5000/api/socket.io/"
echo ""
echo " Comandos teis:"
echo "   Ver logs: tail -f flask.log"
echo "   Verificar processo: ps -p $FLASK_PID"
echo "   Parar servidor: kill \$(cat flask.pid)"
echo "   Restart: ./deploy.sh"
