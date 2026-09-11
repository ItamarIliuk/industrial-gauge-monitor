import pytest
import base64
import json
import os
from unittest.mock import patch, MagicMock

@pytest.fixture
def client():
    # Garantimos que a pasta root/cloud esteja acessível para importações dos testes
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'cloud'))
    
    # Limpa instâncias anteriores se houver cache de importação
    if 'main' in sys.modules:
        del sys.modules['main']
        
    from main import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def create_pubsub_envelope(payload):
    """Helper para criar o envelope Base64 do Pub/Sub."""
    data_str = json.dumps(payload).encode("utf-8")
    data_b64 = base64.b64encode(data_str).decode("utf-8")
    return {"message": {"data": data_b64}}

@patch('google.cloud.bigquery.Client')
@patch('google.cloud.firestore.Client')
def test_low_confidence_discard(mock_firestore, mock_bq, client):
    """AI Safety: Garante descarte de leitura com baixa confiança (0.4) no BQ mas atualiza Firestore."""
    payload = {
        "device_id": "test-01",
        "telemetry": {"confianca_leitura": 0.4, "alerta_visibilidade": False}
    }
    mock_db = MagicMock()
    mock_firestore.return_value = mock_db
    
    response = client.post('/', json=create_pubsub_envelope(payload))
    
    assert response.status_code == 200
    # BigQuery não é atualizado para evitar ruído histórico
    mock_bq.return_value.insert_rows_json.assert_not_called()
    # Firestore é atualizado com status LOW_CONFIDENCE para notificar a UI
    mock_db.collection.assert_called_once()

@patch('google.cloud.bigquery.Client')
@patch('google.cloud.firestore.Client')
def test_visibility_alert_discard(mock_firestore, mock_bq, client):
    """AI Safety: Garante descarte no BigQuery quando a IA sinaliza obstrução."""
    payload = {
        "device_id": "test-01",
        "telemetry": {"confianca_leitura": 0.99, "alerta_visibilidade": True}
    }
    
    # Mock Firestore collection for updating visibility status
    mock_db = MagicMock()
    mock_firestore.return_value = mock_db
    
    response = client.post('/', json=create_pubsub_envelope(payload))
    assert response.status_code == 200
    # BigQuery não deve ser chamado
    mock_bq.return_value.insert_rows_json.assert_not_called()
    # Firestore deve ser chamado para atualizar o dashboard
    mock_db.collection.assert_called_once()

@patch('google.cloud.bigquery.Client')
@patch('google.cloud.firestore.Client')
def test_hallucination_range_check(mock_firestore, mock_bq, client):
    """Robustez: Bloqueia valores fisicamente impossíveis (9999 BAR) no BQ mas registra RANGE_ERROR no Firestore."""
    payload = {
        "device_id": "test-01",
        "telemetry": {
            "data_bar": {"valor": 9999}, # Alucinação
            "confianca_leitura": 0.99,
            "alerta_visibilidade": False
        }
    }
    mock_db = MagicMock()
    mock_firestore.return_value = mock_db
    
    response = client.post('/', json=create_pubsub_envelope(payload))
    assert response.status_code == 200
    # Verifica se a gravação histórica no BQ é pulada
    mock_bq.return_value.insert_rows_json.assert_not_called()
    # Verifica se Firestore é atualizado com o status de erro
    mock_db.collection.assert_called_once()

@patch('google.cloud.firestore.Client')
@patch('google.cloud.bigquery.Client')
def test_database_error_returns_500(mock_bq, mock_firestore, client):
    """Garante que falhas no Firestore retornam HTTP 500 para retentativa do Pub/Sub."""
    mock_db = MagicMock()
    mock_db.collection.side_effect = Exception("Firestore connection timeout")
    mock_firestore.return_value = mock_db
    
    payload = {
        "device_id": "test-01",
        "telemetry": {
            "data_bar": {"valor": 5.0},
            "data_psi": {"valor": 72.5},
            "confianca_leitura": 0.95,
            "alerta_visibilidade": False
        }
    }
    
    response = client.post('/', json=create_pubsub_envelope(payload))
    assert response.status_code == 500
    assert b"Internal Server Error" in response.data

def test_no_hardcoded_secrets_cloud():
    """Estático: Garante que o Cloud Run usa apenas Variáveis de Ambiente."""
    cloud_file = os.path.join(os.path.dirname(__file__), "..", "cloud", "main.py")
    if os.path.exists(cloud_file):
        with open(cloud_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert "os.getenv" in content or "os.environ" in content
            assert 'project_id = "' not in content # Não deve ter o ID do projeto fixo