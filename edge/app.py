import os
import cv2
import time
import json
import logging
import datetime
import numpy as np
from google.cloud import pubsub_v1
from pydantic import BaseModel, Field

# Backend de inferência: "gemini" (Vertex AI, nuvem) ou "cosmos" (NVIDIA Cosmos3 NIM local + geometria).
GAUGE_BACKEND = os.getenv("GAUGE_BACKEND", "gemini").lower()

# Configuração de Logging para ambiente industrial
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s'
)
logger = logging.getLogger("GaugeEdgeAgent")

# Configurações de ROI parametrizáveis (LGPD Compliance)
ROI_Y = (
    int(os.getenv("ROI_Y_START", "150")),
    int(os.getenv("ROI_Y_END", "450"))
)
ROI_X = (
    int(os.getenv("ROI_X_START", "200")),
    int(os.getenv("ROI_X_END", "500"))
)

# Resolução de referência onde a ROI base foi calibrada (640x480)
BASE_WIDTH = int(os.getenv("ROI_BASE_WIDTH", "640"))
BASE_HEIGHT = int(os.getenv("ROI_BASE_HEIGHT", "480"))

# Configurações de Resolução de Captura da Câmera (Padrão 1280x720 HD)
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "720"))

# Esquema de saída compartilhado por todos os backends
from gauge_schema import ScaleReading, GaugeReading  # noqa: E402,F401
import gemini_backend  # noqa: E402

class GaugeAgent:
    def __init__(self):
        # Parametrização do Device ID
        self.device_id = os.getenv("DEVICE_ID", "manometro-caldeira-01")
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.topic_id = os.getenv("TOPIC_ID")
        self.location = "global" # Localização global exigida para Gemini 3 Preview
        
        if not self.topic_id:
            raise EnvironmentError("Variável de ambiente TOPIC_ID não definida.")

        self.backend = GAUGE_BACKEND
        if self.backend not in ("gemini", "cosmos"):
            raise EnvironmentError(f"GAUGE_BACKEND inválido: '{self.backend}' (use 'gemini' ou 'cosmos').")

        if self.backend == "gemini":
            # Inicialização Novo SDK Google GenAI (MaaS)
            from google import genai
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location
            )
        else:
            # NVIDIA Cosmos3 NIM local: a imagem não sai do dispositivo de borda
            import cosmos_backend
            self.client = cosmos_backend.CosmosClient()
            logger.info(f"Backend Cosmos3 NIM em {self.client.url}")

        # Modelo travado para evitar desvios comportamentais (Model Drift)
        self.model_id = os.getenv("MODEL_ID", "gemini-3.6-flash")
        #self.model_id = os.getenv("MODEL_ID", "gemini-3.1-pro-preview")
        
        # Inicialização Pub/Sub
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_id)
        
        self.prompt = gemini_backend.GEMINI_PROMPT

    def capture_and_crop(self):
        """Captura imagem da câmera em tempo real (ou simulação se solicitado), salva imagens de debug e aplica ROI para LGPD."""
        use_sim = os.getenv("USE_SIMULATION_IMAGE", "false").lower() in ("true", "1", "yes")
        test_img_path = os.getenv("SIMULATION_IMAGE_PATH", "20260518_200005.jpg")
        frame = None
        used_index = None

        if not use_sim:
            # Índice preferido configurável via env var (CAMERA_INDEX)
            # IMPORTANTE: Se CAMERA_INDEX for definido explicitamente, usa SOMENTE esse índice.
            # Isso evita que o sistema alterne entre câmeras disponíveis (ex: onboard vs USB).
            preferred_index = int(os.getenv("CAMERA_INDEX", "0"))
            camera_index_is_explicit = "CAMERA_INDEX" in os.environ

            # Se o índice foi explicitamente configurado, não faz fallback para outros índices.
            # Se não foi configurado, tenta 0, 1, 2, 3 como antes (modo de descoberta automática).
            if camera_index_is_explicit:
                indices_to_try = [preferred_index]
                logger.info(f"CAMERA_INDEX definido explicitamente: usando SOMENTE o índice {preferred_index}.")
            else:
                indices_to_try = [preferred_index] + [i for i in range(4) if i != preferred_index]
                logger.info(f"CAMERA_INDEX não definido: tentando índices {indices_to_try} em ordem.")

            def capture_from_backend(idx, backend_flag, backend_name):
                """Abre a câmera uma única vez no backend dado e tenta HD depois SD.
                backend_flag: cv2.CAP_DSHOW para DirectShow, ou None para backend padrão.
                Retorna (frame, resolucao_str) ou (None, None).
                """
                cam_id = idx + backend_flag if backend_flag is not None else idx
                cap = cv2.VideoCapture(cam_id)
                if not cap.isOpened():
                    logger.debug(f"Câmera índice {idx} ({backend_name}): não abriu.")
                    return None, None

                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

                for width, height in [(CAMERA_WIDTH, CAMERA_HEIGHT), (640, 480)]:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                    # Warmup: descarta frames iniciais de auto-exposição do sensor
                    best_frame = None
                    for i in range(15):
                        ret, f = cap.read()
                        if ret and f is not None:
                            best_frame = f
                            if i >= 5 and f.max() > 5:
                                break  # Frame válido após warmup
                        time.sleep(0.04)

                    if best_frame is not None and best_frame.max() > 5:
                        cap.release()
                        res_str = f"{actual_w}x{actual_h}"
                        logger.debug(f"Câmera índice {idx} ({backend_name} {res_str}): frame válido, max_pixel={best_frame.max()}")
                        return best_frame, f"{backend_name} {res_str}"
                    else:
                        px_max = best_frame.max() if best_frame is not None else "N/A"
                        logger.debug(f"Câmera índice {idx} ({backend_name} {actual_w}x{actual_h}): frame inválido (max={px_max}). Tentando SD...")

                cap.release()
                return None, None

            for idx in indices_to_try:
                # Tenta DirectShow primeiro (melhor qualidade no Windows), depois backend padrão.
                # Entre backends, aguarda 1s para o SO liberar o dispositivo.
                backends = [
                    (cv2.CAP_DSHOW, "DirectShow MJPEG"),
                    (None,          "Padrão MJPEG"),
                ]
                for backend_flag, backend_name in backends:
                    f, res_str = capture_from_backend(idx, backend_flag, backend_name)
                    if f is not None:
                        frame = f
                        used_index = f"Índice {idx} ({res_str})"
                        break
                    time.sleep(1.0)  # Pausa para o SO liberar o dispositivo entre backends

                if frame is not None:
                    break
                else:
                    logger.warning(f"Câmera índice {idx}: todos os backends falharam.")



        if frame is not None:
            logger.info(f"📸 CÂMERA AO VIVO ATIVA: Capturada imagem em tempo real ({used_index}) com resolução {frame.shape[1]}x{frame.shape[0]}!")
        else:
            if os.path.exists(test_img_path):
                logger.warning(f"⚠️ Nenhuma câmera ao vivo respondeu. Usando imagem de simulação: '{test_img_path}'")
                frame = cv2.imread(test_img_path)
            elif os.path.exists(os.path.join("debug_captures", "ultimo_frame_alinhamento.jpg")):
                fallback_path = os.path.join("debug_captures", "ultimo_frame_alinhamento.jpg")
                logger.warning(f"⚠️ Usando imagem de fallback: '{fallback_path}'")
                frame = cv2.imread(fallback_path)

        if frame is None:
            raise RuntimeError("Não foi possível acessar a câmera do dispositivo nem carregar imagem de teste.")

        # Cálculo dinâmico e proporcional da ROI com base na resolução real do frame
        h, w = frame.shape[:2]
        scale_x = w / float(BASE_WIDTH)
        scale_y = h / float(BASE_HEIGHT)

        crop_y1 = max(0, min(int(round(ROI_Y[0] * scale_y)), h - 1))
        crop_y2 = max(crop_y1 + 1, min(int(round(ROI_Y[1] * scale_y)), h))
        crop_x1 = max(0, min(int(round(ROI_X[0] * scale_x)), w - 1))
        crop_x2 = max(crop_x1 + 1, min(int(round(ROI_X[1] * scale_x)), w))

        # Aplicação do Crop proporcional (ROI_Y, ROI_X)
        cropped_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        
        # Gravação de Imagens de Debug para Alinhamento e Validação da Câmera
        debug_dir = "debug_captures"
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
            
        # 1. Frame original com o retângulo verde da ROI desenhado
        debug_frame = frame.copy()
        cv2.rectangle(
            debug_frame,
            (crop_x1, crop_y1),
            (crop_x2, crop_y2),
            (0, 255, 0), # Verde
            2
        )
        cv2.imwrite(os.path.join(debug_dir, "ultimo_frame_alinhamento.jpg"), debug_frame)
        
        # 2. Frame recortado (exatamente o que vai para a IA)
        cv2.imwrite(os.path.join(debug_dir, "ultimo_crop_enviado.jpg"), cropped_img)
        logger.info(f"Imagens de debug atualizadas em: {debug_dir}/ (verifique ultimo_frame_alinhamento.jpg e ultimo_crop_enviado.jpg)")

        # Encode para JPEG para envio via API
        _, buffer = cv2.imencode('.jpg', cropped_img)
        return buffer.tobytes()

    def process_inference(self, image_bytes):
        """Envia imagem para o modelo multimodal (Gemini via MaaS API ou Cosmos3 local) com esquema estruturado."""
        if self.backend == "cosmos":
            import cosmos_backend
            ai_json = GaugeReading.model_validate(
                cosmos_backend.read_gauge(image_bytes, client=self.client)
            ).model_dump()
            logger.info(f"Retorno Cosmos3 (Validado via Pydantic): {json.dumps(ai_json, indent=2, ensure_ascii=False)}")
            return ai_json

        ai_json = gemini_backend.read_gauge(image_bytes, self.client, self.model_id, self.prompt)
        logger.info(f"Retorno da IA (Validado via Pydantic): {json.dumps(ai_json, indent=2, ensure_ascii=False)}")
        return ai_json

    def publish_data(self, ai_json):
        """Enriquece o JSON e publica no GCP Pub/Sub e/ou no processador local."""
        payload = {
            "device_id": self.device_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "telemetry": ai_json
        }
        
        data_str = json.dumps(payload).encode("utf-8")
        
        # 1. Envio para GCP Pub/Sub NATIVO
        try:
            future = self.publisher.publish(self.topic_path, data_str)
            logger.info(f"🚀 Publicado no GCP Pub/Sub com Sucesso: {future.result()}")
        except Exception as pe:
            logger.error(f"Erro ao publicar no GCP Pub/Sub: {str(pe)}")

        # 2. Envio opcional direto para o Cloud Router local (se dev-cloud estiver rodando)
        local_url = os.getenv("LOCAL_CLOUD_URL", "http://localhost:8080")
        try:
            import urllib.request
            import base64
            b64_data = base64.b64encode(data_str).decode('utf-8')
            envelope = json.dumps({"message": {"data": b64_data}}).encode('utf-8')
            req = urllib.request.Request(
                local_url,
                data=envelope,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Telemetria sincronizada com o Cloud Processor local ({local_url}) -> Firestore/BigQuery atualizados!")
        except Exception:
            # Silencioso se dev-cloud local não estiver aberto no momento
            pass
        except KeyboardInterrupt:
            # Re-lança KeyboardInterrupt para que Ctrl+C sempre encerre o agente corretamente.
            # (KeyboardInterrupt é BaseException, não Exception — não é capturado pelo bloco acima)
            raise

    def run_cycle(self):
        """Ciclo único de execução com tratamento de erros."""
        try:
            logger.info("Iniciando ciclo de leitura...")
            
            # 1. Captura e Crop
            img_bytes = self.capture_and_crop()
            
            # 2. IA Inference
            ai_result = self.process_inference(img_bytes)
            
            # 3. Publicação
            self.publish_data(ai_result)
            
            logger.info("Ciclo finalizado com sucesso.")
            
        except Exception as e:
            logger.error(f"Erro no ciclo de execução: {str(e)}")

    def start(self):
        """Loop infinito com espera configurável (padrão 1 minuto / 60 segundos)."""
        interval = int(os.getenv("CYCLE_INTERVAL", "60"))
        logger.info(f"Agente {self.device_id} iniciado. Intervalo: {interval} segundos.")
        while True:
            self.run_cycle()
            logger.info(f"Aguardando {interval} segundos para o próximo ciclo...")
            time.sleep(interval)

if __name__ == "__main__":
    agent = GaugeAgent()
    agent.start()
