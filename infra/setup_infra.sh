#!/bin/bash

# --- CONFIGURAÇÕES DO PROJETO ---
PROJECT_ID="seu-projeto-id" # Substitua pelo seu ID do GCP
REGION="us-central1"
SERVICE_ACCOUNT_NAME="smart-cam-sa"
SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Iniciando provisionamento da infraestrutura IoT no projeto: $PROJECT_ID"

# 1. Habilitar APIs Necessárias
echo "Ativando APIs do Google Cloud..."
gcloud services enable \
    pubsub.googleapis.com \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com --project=$PROJECT_ID

# 2. Configurar Pub/Sub
echo "Criando Tópico do Pub/Sub..."
gcloud pubsub topics create telemetry-manometer --project=$PROJECT_ID

# 3. Configurar BigQuery
echo "Criando Dataset e Tabela no BigQuery..."
# Cria o dataset
bq --project_id=$PROJECT_ID mk --dataset telemetry_db

# Cria a tabela com o schema definido
bq --project_id=$PROJECT_ID mk --table telemetry_db.manometer_readings \
    timestamp:TIMESTAMP,device_id:STRING,pressao_bar:FLOAT,pressao_psi:FLOAT,confianca:FLOAT

# 4. Criar Conta de Serviço (IAM)
echo "Configurando Service Account para o Edge Agent..."
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
    --display-name="Service Account para Câmeras Inteligentes IoT" \
    --project=$PROJECT_ID

# 5. Atribuir Permissões (Princípio do Menor Privilégio)
echo "Atribuindo permissões de IAM..."

# Permissão para publicar no Pub/Sub
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/pubsub.publisher"

# Permissão para usar Vertex AI (Inferência Multimodal)
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/aiplatform.user"

# Permissao para criar jobs de query no BigQuery (leitura pelo dashboard/CLI)
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigquery.jobUser"

# Permissao para ler dados das tabelas BigQuery
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigquery.dataViewer"

# 6. Gerar Chave JSON para o Dispositivo Edge
echo "Gerando chave de seguranca para o dispositivo..."

# A chave e salva FORA do diretorio do projeto para nao ser commitada acidentalmente
GCP_CONFIG_DIR="$HOME/.config/gcp"
KEY_OUTPUT_PATH="$GCP_CONFIG_DIR/edge-sa-key.json"
mkdir -p $GCP_CONFIG_DIR

gcloud iam service-accounts keys create $KEY_OUTPUT_PATH \
    --iam-account=$SA_EMAIL \
    --project=$PROJECT_ID

echo "Chave salva em: $KEY_OUTPUT_PATH (FORA do repositorio)"
echo "Configure: export GOOGLE_APPLICATION_CREDENTIALS=$KEY_OUTPUT_PATH"

# 7. Deploy do Microsserviço no Cloud Run
echo "Realizando deploy do processador no Cloud Run..."
gcloud run deploy gauge-processor \
    --source ./cloud \
    --region $REGION \
    --project $PROJECT_ID \
    --set-env-vars TOPIC_ID=telemetry-manometer,BQ_DATASET=telemetry_db,BQ_TABLE=manometer_readings \
    --allow-unauthenticated \
    --description="Processador de telemetria de manômetros via Pub/Sub"

# Obtém a URL gerada do Cloud Run
SERVICE_URL=$(gcloud run services describe gauge-processor --region $REGION --project $PROJECT_ID --format="value(status.url)")

# 8. Criar Subscription Pub/Sub Push para o Cloud Run
echo "Criando Subscription Pub/Sub Push para o Cloud Run..."
gcloud pubsub subscriptions create telemetry-manometer-sub \
    --topic telemetry-manometer \
    --push-endpoint $SERVICE_URL \
    --project $PROJECT_ID

echo "--------------------------------------------------------"
echo "✅ Infraestrutura provisionada com sucesso!"
echo "📍 Topico: telemetry-manometer"
echo "📍 Subscription Push: telemetry-manometer-sub -> $SERVICE_URL"
echo "📍 Tabela BQ: telemetry_db.manometer_readings"
echo "🔑 Chave gerada em: $KEY_OUTPUT_PATH (FORA do repositorio - nao sera commitada)"
echo "   Configure: export GOOGLE_APPLICATION_CREDENTIALS=$KEY_OUTPUT_PATH"
echo "--------------------------------------------------------"
