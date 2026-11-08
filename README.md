# Industrial Gauge Monitor

Sistema IoT de visão computacional na borda para monitoramento de manômetros industriais.
Integra dispositivos de borda (Edge) com a nuvem GCP usando AI multimodal.

## Módulos
- **Edge**: Captura de imagem e processamento com Vertex AI (Gemma 4 Multimodal).
- **Cloud**: Cloud Run (Flask) consumindo mensagens Pub/Sub via push.
- **UI**: Dashboard SCADA construído com Streamlit.
- **Infra**: Scripts Terraform/gcloud para provisionamento de recursos GCP.

## 🚀 Comandos para Execução

Você pode executar a aplicação utilizando o **PowerShell** (no Windows) ou o **Makefile** (no Linux/macOS/Git Bash).

---

### 1. 🟢 Via PowerShell (`run_project.ps1`) - Recomendado para Windows

| Comando | Descrição |
| :--- | :--- |
| `.\run_project.ps1 setup` | Cria o ambiente virtual (`.venv`), instala dependências e executa o setup da infraestrutura GCP. |
| `.\run_project.ps1 test` | Executa a suíte de testes unitários e de integração com `pytest`. |
| `.\run_project.ps1 dev-cloud` | Inicia o serviço Cloud Router (Flask) localmente na porta 8080. |
| `.\run_project.ps1 dev-ui` | Inicia a interface gráfica Dashboard SCADA no navegador via `Streamlit`. |
| `.\run_project.ps1 dev-edge` | Inicia o Agente de Borda (Edge Agent) para captura e processamento por câmera. |
| `.\run_project.ps1 query-bq` | Consulta as últimas leituras de telemetria armazenadas no Google BigQuery. |

---

### 2. 🐧 Via Makefile - Recomendado para Linux / macOS / Bash

| Comando | Descrição |
| :--- | :--- |
| `make setup` | Configura infraestrutura GCP e instala todas as dependências Python. |
| `make test` | Roda a suíte de testes com `pytest`. |
| `make dev-cloud` | Inicia o Cloud Router (Flask) na porta 8080. |
| `make dev-ui` | Inicia o Dashboard SCADA (Streamlit). |
| `make dev-edge` | Inicia o Agente Edge (Câmera IoT). |

---

### 3. 🐍 Execução Direta via Terminal (Python / CLI)

Se preferir rodar os módulos manualmente:

* **Instalar dependências:**
  ```bash
  pip install -r edge/requirements.txt -r cloud/requirements.txt -r ui/requirements.txt
  ```

* **Rodar o Cloud Router (Flask):**
  ```bash
  cd cloud
  FLASK_APP=main.py flask run --port=8080
  ```

* **Rodar o Dashboard SCADA (Streamlit):**
  ```bash
  cd ui
  streamlit run dashboard_scada.py
  ```

* **Rodar o Agente Edge (Câmera IoT):**
  ```bash
  cd edge
  python app.py
  ```

* **Rodar os Testes:**
  ```bash
  PYTHONPATH=./edge:./cloud pytest tests/ -v -s
  ```
---

## 🟩 Backend local NVIDIA Cosmos3 (sem nuvem)

O Edge Agent aceita dois backends de inferência, escolhidos por `GAUGE_BACKEND`:

| Backend | Onde roda | Imagem sai da planta? | Custo de IA |
| :--- | :--- | :--- | :--- |
| `gemini` (padrão) | Vertex AI (Gemini 3.6 Flash) | Sim | por token |
| `cosmos` | NVIDIA Cosmos3 Edge Reasoner (NIM) na GPU local | **Não** | zero (hardware próprio) |

O backend `cosmos` ([edge/cosmos_backend.py](edge/cosmos_backend.py)) funciona assim: o **Cosmos3 localiza o mostrador**, e uma **medição geométrica da agulha** lê o valor. A ponta fina é o lado mais longo; o contrapeso é ignorado. O ângulo é convertido pelas marcas impressas do mostrador (`GAUGE_CALIB`). A saída usa o **mesmo esquema `GaugeReading`** do Gemini, então Pub/Sub, Firestore, BigQuery e o dashboard não mudam.

```bash
# NIM do Cosmos3 rodando em http://localhost:8000 (ver projeto manometro-iot/setup)
GAUGE_BACKEND=cosmos COSMOS_URL=http://localhost:8000 python edge/app.py
```

### Comparação entre backends
```bash
python bench/compare.py <pasta_fotos> --backends cosmos,gemini
```
Usa o mesmo `process_inference` do agente, sem câmera e sem Pub/Sub, e grava `bench/results.csv` com erro, confiança e latência. As referências ficam em `bench/reference_visual.csv`.

Resultado do Cosmos3 em 13 fotos (RTX 4090, referência visual de ±0,2 bar): **MAE de 0,09 bar** no geral, **0,13 bar** com pressão e erro máximo de 0,27 bar, com **cerca de 0,4 s por leitura**.
