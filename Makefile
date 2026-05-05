.DEFAULT_GOAL := help

COMPOSE_BASE          := docker compose
COMPOSE_MONITORING    := docker compose -f ark/monitoring/docker-compose.monitoring.yml
COMPOSE_CROWDSEC      := docker compose -f ark/crowdsec/docker-compose.crowdsec.yml

.PHONY: help dev dev-down logs ps restart \
        test test-backend test-frontend lint \
        sdk-build sdk-smoke \
        monitoring-up monitoring-down monitoring-logs \
        crowdsec-up crowdsec-down crowdsec-logs \
        ansible-deps ansible-check ansible-apply \
        retencao-aplicar

help:
	@echo "Alvos disponiveis:"
	@echo "  dev              sobe frontend + backend + influxdb"
	@echo "  dev-down         para e remove containers locais"
	@echo "  logs             tail nos logs do backend"
	@echo "  ps               estado dos containers"
	@echo "  restart          reinicia backend e frontend"
	@echo "  test             roda backend+frontend"
	@echo "  test-backend     unittest discover no backend"
	@echo "  test-frontend    vitest + lint"
	@echo "  lint             so o lint do frontend"
	@echo "  sdk-build        empacota o SDK (dist/sdk/)"
	@echo "  sdk-smoke        smoke test do bundle"
	@echo "  monitoring-up    sobe Prometheus + Grafana"
	@echo "  monitoring-down  para stack de monitoring"
	@echo "  crowdsec-up      sobe CrowdSec agent"
	@echo "  crowdsec-down    para CrowdSec"
	@echo "  ansible-deps     instala collections fixadas em requirements.yml"
	@echo "  ansible-check    playbook em dry-run"
	@echo "  ansible-apply    aplica playbook no inventario"
	@echo "  retencao-aplicar configura retencao do bucket (use DIAS=90)"

dev:
	$(COMPOSE_BASE) up --build -d

dev-down:
	$(COMPOSE_BASE) down

logs:
	$(COMPOSE_BASE) logs -f backend

ps:
	$(COMPOSE_BASE) ps

restart:
	$(COMPOSE_BASE) restart backend frontend

test: test-backend test-frontend

test-backend:
	$(COMPOSE_BASE) exec -T backend python -m unittest discover -s . -p 'test_*.py'

test-frontend:
	$(COMPOSE_BASE) exec -T frontend sh -c 'cd /app && npm run test && npm run lint'

lint:
	$(COMPOSE_BASE) exec -T frontend sh -c 'cd /app && npm run lint'

sdk-build:
	$(COMPOSE_BASE) exec -T frontend sh -c 'cd /app && npm run build:sdk'

sdk-smoke:
	$(COMPOSE_BASE) exec -T frontend sh -c 'cd /app && node scripts/smoke-sdk-bundle.mjs'

monitoring-up:
	$(COMPOSE_MONITORING) up -d

monitoring-down:
	$(COMPOSE_MONITORING) down

monitoring-logs:
	$(COMPOSE_MONITORING) logs -f

crowdsec-up:
	$(COMPOSE_CROWDSEC) up -d

crowdsec-down:
	$(COMPOSE_CROWDSEC) down

crowdsec-logs:
	$(COMPOSE_CROWDSEC) logs -f

ansible-deps:
	ansible-galaxy collection install -r ark/ansible/requirements.yml

ansible-check:
	cd ark/ansible && ansible-playbook -i inventory.ini playbook.yml --check

ansible-apply:
	cd ark/ansible && ansible-playbook -i inventory.ini playbook.yml

retencao-aplicar:
	$(COMPOSE_BASE) exec -T backend python scripts/configurar_retencao.py --dias $(or $(DIAS),90)
