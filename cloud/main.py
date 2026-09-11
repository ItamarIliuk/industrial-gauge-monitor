import base64
import json
import logging
import os
from datetime import datetime

from flask import Flask, request
from google.cloud import bigquery, firestore

# Configuração de Logs Estruturados
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Tenta pegar o ID do projeto de várias fontes possíveis no GCP
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
BQ_DATASET = os.getenv("BQ_DATASET", "telemetry_db")
BQ_TABLE = os.getenv("BQ_TABLE", "manometer_readings")
FIRESTORE_COLLECTION = "realtime_gauges"

# Inicialização dos Clientes (Lazy Loading)
_bq_client = None
_db_client = None

def get_bq_client():
    global _bq_client
    if _bq_client is None:
        try:
            if PROJECT_ID:
                _bq_client = bigquery.Client(project=PROJECT_ID)
            else:
                _bq_client = bigquery.Client()
        except Exception as e:
            logger.error(f"Erro ao inicializar cliente BigQuery: {str(e)}")
    return _bq_client

def get_firestore_client():
    global _db_client
    if _db_client is None:
        if PROJECT_ID:
            _db_client = firestore.Client(project=PROJECT_ID)
        else:
            _db_client = firestore.Client()
    return _db_client

def safe_float(value, field_name="unknown"):
    if value is None: return 0.0
    if isinstance(value, (int, float)): return float(value)
    val_str = str(value).lower()
    mapping = {"alta": 0.99, "media": 0.50, "baixa": 0.20, "nula": 0.0, "boa": 0.90}
    if val_str in mapping: return mapping[val_str]
    try: return float(value)
    except: return 0.0

@app.route("/", methods=["POST"])
def process_pubsub_message():
    envelope = request.get_json()
    if not envelope: return "Bad Request", 400

    pubsub_message = envelope.get("message", {})
    if "data" not in pubsub_message: return "OK", 200

    try:
        try:
            raw_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
            payload = json.loads(raw_data)
        except Exception as parse_err:
            logger.error(f"Erro de parser do payload: {str(parse_err)}")
            return f"Bad Request - Invalid JSON: {str(parse_err)}", 400
        
        device_id = payload.get("device_id", "manometro-caldeira-01")
        timestamp = payload.get("timestamp")
        telemetry = payload.get("telemetry", {})
        
        confianca = safe_float(telemetry.get("confianca_leitura"), "confianca")
        alerta_vis = telemetry.get("alerta_visibilidade", False)
        
        logger.info(f"PROCESSANDO: {device_id} | Conf: {confianca} | Visib: {alerta_vis}")

        # Camada de Validação
        # 1. Threshold mínimo de 0.50
        if confianca < 0.50:
            logger.warning(f"CONFIANÇA BAIXA ({confianca}) - Atualizando Firestore com status LOW_CONFIDENCE")
            try:
                db = get_firestore_client()
                doc_ref = db.collection(FIRESTORE_COLLECTION).document(device_id)
                doc_ref.set({
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "status": "LOW_CONFIDENCE",
                    "last_reading": {
                        "confianca": confianca
                    }
                }, merge=True)
            except Exception as fe:
                logger.error(f"Erro ao salvar status de baixa confiança no Firestore: {str(fe)}")
            return "Processed - Low confidence registered", 200

        bar_val = safe_float(telemetry.get("data_bar", {}).get("valor"), "bar")
        psi_val = safe_float(telemetry.get("data_psi", {}).get("valor"), "psi")

        # 2. Validação física de pressão (0 a 17 BAR e 0 a 250 PSI)
        if bar_val < 0.0 or bar_val > 17.0 or psi_val < 0.0 or psi_val > 250.0:
            logger.warning(f"VALORES ANÔMALOS (BAR: {bar_val}, PSI: {psi_val}) - Atualizando Firestore com status RANGE_ERROR")
            try:
                db = get_firestore_client()
                doc_ref = db.collection(FIRESTORE_COLLECTION).document(device_id)
                doc_ref.set({
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "status": "RANGE_ERROR",
                    "last_reading": {
                        "confianca": confianca
                    }
                }, merge=True)
            except Exception as fe:
                logger.error(f"Erro ao salvar status de erro de limite no Firestore: {str(fe)}")
            return "Processed - Physical range check failed registered", 200

        # --- PRIORIDADE A: FIRESTORE (TEMPO REAL) ---
        try:
            db = get_firestore_client()
            doc_ref = db.collection(FIRESTORE_COLLECTION).document(device_id)
            doc_ref.set({
                "last_reading": {"bar": bar_val, "psi": psi_val, "confianca": confianca},
                "updated_at": firestore.SERVER_TIMESTAMP,
                "status": "NORMAL" if not alerta_vis else "CHECK_VISIBILITY"
            }, merge=True)
            logger.info(f"FIRESTORE ATUALIZADO: {bar_val} BAR")
        except Exception as fe:
            logger.error(f"Erro Firestore: {str(fe)}")
            raise fe

        # --- PRIORIDADE B: BIGQUERY (HISTORICO) ---
        # Se houver obstrução visual, não gravamos no BigQuery para evitar poluir dados históricos
        if not alerta_vis:
            client_bq = get_bq_client()
            if client_bq:
                try:
                    target_project = PROJECT_ID or client_bq.project
                    table_ref = f"{target_project}.{BQ_DATASET}.{BQ_TABLE}"
                    row_to_insert = [{"timestamp": timestamp, "device_id": device_id, "pressao_bar": bar_val, "pressao_psi": psi_val, "confianca": confianca}]
                    errors = client_bq.insert_rows_json(table_ref, row_to_insert)
                    if errors:
                        logger.error(f"Erro BigQuery insert em {table_ref}: {errors}")
                        raise RuntimeError(f"Erro BigQuery insert: {errors}")
                    logger.info(f"BIGQUERY INSERIDO COM SUCESSO na tabela {table_ref}")
                except Exception as be:
                    logger.error(f"Erro BigQuery: {str(be)}")
                    raise be
        else:
            logger.info("Gravação no BigQuery pulada devido a alerta de visibilidade.")

        return "Processed", 200

    except Exception as e:
        logger.error(f"Erro Geral no processamento: {str(e)}")
        return f"Internal Server Error: {str(e)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
