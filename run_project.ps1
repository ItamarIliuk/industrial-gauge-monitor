# Orquestrador de Projeto Industrial IoT (PowerShell)

# Variáveis de Ambiente
if (-not $env:GOOGLE_CLOUD_PROJECT) {
    $env:GOOGLE_CLOUD_PROJECT = "seu-projeto-gcp"
}
$env:GOOGLE_CLOUD_REGION = "us-central1"
$env:TOPIC_ID = "telemetry-manometer"
$env:BQ_DATASET = "telemetry_db"
$env:BQ_TABLE = "manometer_readings"
$env:PYTHONPATH = ".;./edge;./cloud"

# Câmera USB fixada no índice 0 (manômetro). Índice 1 = onboard do notebook (no seu setup).
# Altere aqui se a câmera mudar de índice (use .\run_project.ps1 test-cameras para verificar).
$env:CAMERA_INDEX = "0"

# Credencial GCP armazenada FORA do repositório (segurança)
# A chave de Service Account não fica dentro da pasta do projeto
$SA_KEY_PATH = "$env:USERPROFILE\.config\gcp\edge-sa-key.json"
if (Test-Path $SA_KEY_PATH) {
    $env:GOOGLE_APPLICATION_CREDENTIALS = $SA_KEY_PATH
    Write-Host "[Auth] GOOGLE_APPLICATION_CREDENTIALS configurado: $SA_KEY_PATH" -ForegroundColor DarkGray
} else {
    Write-Warning "[Auth] Chave GCP não encontrada em: $SA_KEY_PATH"
    Write-Warning "[Auth] Execute: gcloud auth application-default login  OU  rode .\infra\setup_infra.ps1 para gerar a chave."
}

$VENV_PYTHON = ".\.venv\Scripts\python.exe"
$VENV_PYTEST = ".\.venv\Scripts\pytest.exe"
$VENV_FLASK  = ".\.venv\Scripts\flask.exe"
$VENV_STREAMLIT = ".\.venv\Scripts\streamlit.exe"
$VENV_PIP    = ".\.venv\Scripts\pip.exe"

function Show-Help {
    Write-Host "Uso: .\run_project.ps1 [comando]" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Comandos disponiveis:"
    Write-Host "  setup        - Configura infra no GCP e instala bibliotecas no .venv"
    Write-Host "  test         - Roda a suite de testes com PyTest"
    Write-Host "  test-cameras - Escaneia cameras disponíveis e salva frames em debug_captures/"
    Write-Host "  dev-cloud    - Inicia o Cloud Router local (Flask)"
    Write-Host "  dev-ui       - Inicia o Dashboard SCADA (Streamlit com BigQuery)"
    Write-Host "  dev-edge     - Inicia o Agente de Borda (Camera, CAMERA_INDEX=$env:CAMERA_INDEX)"
    Write-Host "  query-bq     - Consulta as leituras salvas no GCP BigQuery via CLI"
}

if ($args.Count -eq 0) {
    Show-Help
    exit
}

$action = $args[0]

switch ($action) {
    "setup" {
        Write-Host ">> Iniciando Setup..." -ForegroundColor Green
        if (-not (Test-Path ".\.venv")) {
            Write-Host ">> Criando ambiente virtual .venv..." -ForegroundColor Cyan
            python -m venv .venv
        }
        
        # Executa o script PowerShell de infra
        if (Test-Path ".\infra\setup_infra.ps1") {
            & .\infra\setup_infra.ps1
        }
        
        Write-Host ">> Instalando dependencias no .venv..." -ForegroundColor Cyan
        & $VENV_PIP install -r edge/requirements.txt
        & $VENV_PIP install -r cloud/requirements.txt
        & $VENV_PIP install -r ui/requirements.txt
        & $VENV_PIP install pytest pytest-mock pyyaml
        break
    }
    
    "test" {
        Write-Host ">> Rodando testes..." -ForegroundColor Green
        if (Test-Path $VENV_PYTEST) {
            & $VENV_PYTEST tests/ -v -s
        } else {
            pytest tests/ -v -s
        }
        break
    }

    "test-cameras" {
        Write-Host ">> Escaneando câmeras disponíveis (CAMERA_INDEX atual: $env:CAMERA_INDEX)..." -ForegroundColor Cyan
        Write-Host "   Verifique as imagens salvas em debug_captures/ para identificar o índice correto." -ForegroundColor Yellow
        if (Test-Path $VENV_PYTHON) {
            & $VENV_PYTHON edge/test_cameras.py
        } else {
            python edge/test_cameras.py
        }
        break
    }

    "dev-cloud" {
        Write-Host ">> Iniciando Flask na porta 8080..." -ForegroundColor Cyan
        $env:FLASK_APP = "cloud/main.py"
        if (Test-Path $VENV_FLASK) {
            & $VENV_FLASK run --port=8080
        } else {
            flask run --port=8080
        }
        break
    }
    
    "dev-ui" {
        Write-Host ">> Iniciando Dashboard SCADA..." -ForegroundColor Cyan
        if (Test-Path $VENV_STREAMLIT) {
            & $VENV_STREAMLIT run ui/dashboard_scada.py
        } else {
            streamlit run ui/dashboard_scada.py
        }
        break
    }
    
    "dev-edge" {
        Write-Host ">> Iniciando Agente de Borda (Camera)..." -ForegroundColor Cyan
        if (Test-Path $VENV_PYTHON) {
            & $VENV_PYTHON edge/app.py
        } else {
            python edge/app.py
        }
        break
    }
    
    "query-bq" {
        Write-Host ">> Lendo registros do GCP BigQuery..." -ForegroundColor Cyan
        if (Test-Path $VENV_PYTHON) {
            & $VENV_PYTHON cloud/query_bigquery.py
        } else {
            python cloud/query_bigquery.py
        }
        break
    }
    
    default {
        Show-Help
        break
    }
}


