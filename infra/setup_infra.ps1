param (
    [Parameter(Mandatory=$false)]
    [string]$PROJECT_ID = $env:GOOGLE_CLOUD_PROJECT,

    [Parameter(Mandatory=$false)]
    [string]$REGION = "us-central1"
)

if ([string]::IsNullOrEmpty($PROJECT_ID)) {
    Write-Error "O PROJECT_ID é obrigatório. Defina a variável de ambiente GOOGLE_CLOUD_PROJECT ou passe como parâmetro (ex: .\setup_infra.ps1 -PROJECT_ID 'seu-projeto')."
    exit 1
}

# Configurações do Projeto
$SERVICE_ACCOUNT_NAME = "smart-cam-sa"
$SA_EMAIL = "${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

Write-Host "Iniciando provisionamento da infraestrutura IoT no projeto: $PROJECT_ID" -ForegroundColor Green

# 1. Habilitar APIs Necessárias
Write-Host "Ativando APIs do Google Cloud..." -ForegroundColor Cyan
gcloud services enable `
    pubsub.googleapis.com `
    aiplatform.googleapis.com `
    bigquery.googleapis.com `
    run.googleapis.com `
    artifactregistry.googleapis.com `
    firestore.googleapis.com `
    cloudbuild.googleapis.com --project=$PROJECT_ID

# 2. Configurar Pub/Sub
Write-Host "Criando Topico do Pub/Sub..." -ForegroundColor Cyan
gcloud pubsub topics create telemetry-manometer --project=$PROJECT_ID

# 3. Configurar BigQuery
Write-Host "Criando Dataset e Tabela no BigQuery..." -ForegroundColor Cyan
# Cria o dataset
bq --project_id=$PROJECT_ID mk --dataset telemetry_db

# Cria a tabela com o schema definido
bq --project_id=$PROJECT_ID mk --table telemetry_db.manometer_readings `
    "timestamp:TIMESTAMP,device_id:STRING,pressao_bar:FLOAT,pressao_psi:FLOAT,confianca:FLOAT"

# 4. Criar Conta de Servico (IAM)
Write-Host "Configurando Service Account para o Edge Agent..." -ForegroundColor Cyan
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME `
    --display-name="Service Account para Cameras Inteligentes IoT" `
    --project=$PROJECT_ID

# 5. Atribuir Permissoes
Write-Host "Atribuindo permissoes de IAM..." -ForegroundColor Cyan

# Pub/Sub Publisher
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/pubsub.publisher"

# Permissao para usar Vertex AI (Inferencia Multimodal)
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/aiplatform.user"

# Permissao para criar jobs de query no BigQuery (leitura pelo dashboard/CLI)
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/bigquery.jobUser"

# Permissao para ler dados das tabelas BigQuery
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/bigquery.dataViewer"

# 6. Gerar Chave JSON
Write-Host "Gerando chave de seguranca para o dispositivo..." -ForegroundColor Cyan

# A chave e salva FORA do diretorio do projeto para nao ser commitada acidentalmente
$GCP_CONFIG_DIR = "$env:USERPROFILE\.config\gcp"
$KEY_OUTPUT_PATH = "$GCP_CONFIG_DIR\edge-sa-key.json"
New-Item -ItemType Directory -Path $GCP_CONFIG_DIR -Force | Out-Null

gcloud iam service-accounts keys create $KEY_OUTPUT_PATH `
    --iam-account=$SA_EMAIL `
    --project=$PROJECT_ID

Write-Host "Chave salva em: $KEY_OUTPUT_PATH (FORA do repositorio)" -ForegroundColor Yellow
Write-Host "Configure a variavel de ambiente GOOGLE_APPLICATION_CREDENTIALS=$KEY_OUTPUT_PATH" -ForegroundColor Yellow

# 7. Deploy do Microsservico no Cloud Run
Write-Host "Realizando deploy do processador no Cloud Run..." -ForegroundColor Cyan
# O comando de deploy usa o diretorio 'cloud' para o contexto do Docker
gcloud run deploy gauge-processor `
    --source ./cloud `
    --region $REGION `
    --project $PROJECT_ID `
    --set-env-vars "TOPIC_ID=telemetry-manometer,BQ_DATASET=telemetry_db,BQ_TABLE=manometer_readings" `
    --allow-unauthenticated `
    --description="Processador de telemetria de manometros via Pub/Sub"

# Obtem a URL gerada do Cloud Run
$SERVICE_URL = (gcloud run services describe gauge-processor --region $REGION --project $PROJECT_ID --format="value(status.url)")

# 8. Criar Subscription Pub/Sub Push para o Cloud Run
Write-Host "Criando Subscription Pub/Sub Push para o Cloud Run..." -ForegroundColor Cyan
gcloud pubsub subscriptions create telemetry-manometer-sub `
    --topic telemetry-manometer `
    --push-endpoint $SERVICE_URL `
    --project $PROJECT_ID

Write-Host "--------------------------------------------------------" -ForegroundColor Green
Write-Host "Infraestrutura provisionada com sucesso!"
Write-Host "Topico: telemetry-manometer"
Write-Host "Subscription Push: telemetry-manometer-sub -> $SERVICE_URL"
Write-Host "Tabela BQ: telemetry_db.manometer_readings"
Write-Host "Chave gerada em: $KEY_OUTPUT_PATH (fora do repositorio - nao sera commitada)"
Write-Host "--------------------------------------------------------"
