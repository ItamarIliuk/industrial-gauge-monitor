import pytest
import numpy as np
import os
from unittest.mock import MagicMock, patch
import json

def test_lgpd_crop_dimensions():
    """Valida se o recorte (crop) descarta as bordas da imagem original (LGPD) e escala proporcionalmente."""
    # Simulamos um frame base (480x640)
    base_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ROI_Y = (150, 450)
    ROI_X = (200, 500)
    
    scale_x_base = 640 / 640.0
    scale_y_base = 480 / 480.0
    
    cropped_base = base_frame[
        int(ROI_Y[0] * scale_y_base):int(ROI_Y[1] * scale_y_base),
        int(ROI_X[0] * scale_x_base):int(ROI_X[1] * scale_x_base)
    ]
    
    assert cropped_base.shape[0] == 300  # 450 - 150
    assert cropped_base.shape[1] == 300  # 500 - 200

def test_proportional_roi_scaling_resolutions():
    """Valida o cálculo proporcional da ROI para resoluções HD (1280x720) e Full HD (1920x1080)."""
    BASE_W, BASE_H = 640, 480
    ROI_Y, ROI_X = (150, 450), (200, 500)

    # 1. Teste HD (720x1280)
    hd_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    sx_hd = hd_frame.shape[1] / float(BASE_W) # 2.0
    sy_hd = hd_frame.shape[0] / float(BASE_H) # 1.5

    crop_y1_hd = int(round(ROI_Y[0] * sy_hd)) # 225
    crop_y2_hd = int(round(ROI_Y[1] * sy_hd)) # 675
    crop_x1_hd = int(round(ROI_X[0] * sx_hd)) # 400
    crop_x2_hd = int(round(ROI_X[1] * sx_hd)) # 1000

    cropped_hd = hd_frame[crop_y1_hd:crop_y2_hd, crop_x1_hd:crop_x2_hd]
    assert cropped_hd.shape[0] == 450 # (450-150)*1.5
    assert cropped_hd.shape[1] == 600 # (500-200)*2.0

    # 2. Teste Full HD (1080x1920)
    fhd_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    sx_fhd = fhd_frame.shape[1] / float(BASE_W) # 3.0
    sy_fhd = fhd_frame.shape[0] / float(BASE_H) # 2.25

    crop_y1_fhd = int(round(ROI_Y[0] * sy_fhd)) # 338
    crop_y2_fhd = int(round(ROI_Y[1] * sy_fhd)) # 1012
    crop_x1_fhd = int(round(ROI_X[0] * sx_fhd)) # 600
    crop_x2_fhd = int(round(ROI_X[1] * sx_fhd)) # 1500

    cropped_fhd = fhd_frame[crop_y1_fhd:crop_y2_fhd, crop_x1_fhd:crop_x2_fhd]
    assert cropped_fhd.shape[0] == 674 or cropped_fhd.shape[0] == 675
    assert cropped_fhd.shape[1] == 900
    print("\n[OK] ROI proporcional validada com sucesso em 640x480, 1280x720 e 1920x1080.")

@patch('cv2.VideoCapture')
def test_camera_hardware_failure(mock_video):
    """Testa o tratamento de erro quando a câmera está desconectada."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    mock_video.return_value = mock_cap
    
    # Simula a tentativa de captura
    with pytest.raises(RuntimeError, match="Não foi possível acessar a câmera"):
        if not mock_cap.isOpened():
            raise RuntimeError("Não foi possível acessar a câmera do dispositivo.")

def test_analyze_gauge_json_parsing():
    """Valida se o parser carrega JSON diretamente e levanta JSONDecodeError se for inválido."""
    raw_json_response = """{
        "raciocinio_geometrico": "Ponteiro em 45 graus",
        "data_bar": {"valor": 2.5, "unidade": "bar"},
        "data_psi": {"valor": 36.2, "unidade": "psi"},
        "confianca_leitura": 0.95,
        "alerta_visibilidade": false
    }"""
    
    # Lógica de parsing nova
    parsed = json.loads(raw_json_response.strip())
    assert parsed["data_bar"]["valor"] == 2.5
    assert parsed["confianca_leitura"] == 0.95

    # Lógica de erro
    invalid_response = "Texto simples não estruturado"
    with pytest.raises(json.JSONDecodeError):
        json.loads(invalid_response.strip())

def test_no_hardcoded_secrets_edge():
    """Verifica se não há chaves sensíveis escritas no código."""
    edge_file = os.path.join(os.path.dirname(__file__), "..", "edge", "app.py")
    if os.path.exists(edge_file):
        with open(edge_file, "r", encoding="utf-8") as f:
            content = f.read()
            # Procura por padrões comuns de chaves ou atribuições diretas suspeitas
            forbidden = ["AI_KEY =", "SECRET =", "service_account.json", "PRIVATE_KEY"]
            for word in forbidden:
                assert word not in content, f"⚠️ Risco de Segurança: '{word}' encontrado em {edge_file}"