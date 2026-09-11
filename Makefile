.PHONY: setup test dev-cloud dev-ui dev-edge

# Variáveis globais de ambiente para desenvolvimento local
export GOOGLE_CLOUD_PROJECT=seu-projeto-id
export TOPIC_ID=telemetry-manometer
export BQ_DATASET=telemetry_db
export BQ_TABLE=manometer_readings

setup:
	@echo "🔧 Configurando Infraestrutura no GCP e instalando dependências locais..."
	cd infra && chmod +x setup_infra.sh && ./setup_infra.sh
	@echo "📦 Instalando dependências Python..."
	pip install -r edge/requirements.txt
	pip install -r cloud/requirements.txt
	pip install -r ui/requirements.txt
	pip install pytest pytest-mock

test:
	@echo "🧪 Rodando Suíte de Testes de Segurança e Integração..."
	# Injeta edge/ e cloud/ no PATH do Python para os testes os encontrarem
	PYTHONPATH=./edge:./cloud pytest tests/ -v -s

dev-cloud:
	@echo "☁️ Iniciando Cloud Router (Flask) localmente na porta 8080..."
	cd cloud && FLASK_APP=main.py flask run --port=8080

dev-ui:
	@echo "📊 Iniciando SCADA Dashboard localmente..."
	cd ui && streamlit run dashboard_scada.py

dev-edge:
	@echo "📸 Iniciando Edge Agent (Câmera IoT)..."
	cd edge && python app.py