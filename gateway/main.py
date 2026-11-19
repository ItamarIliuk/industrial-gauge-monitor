"""Gateway de dispositivos IoT de captura (ex.: ESP32-S3 + OV2640) para leitura de manômetros.

Os dispositivos só capturam e enviam a imagem (JPEG) por HTTP; toda a análise roda aqui,
com o backend configurado por dispositivo (Cosmos3 local ou Gemini), e o resultado segue
para o mesmo pipeline do projeto (Pub/Sub -> Firestore/BigQuery -> Dashboard SCADA).

Endpoints
  POST   /v1/ingest/{device_id}          corpo = JPEG cru (Content-Type: image/jpeg), header X-Device-Token
  POST   /v1/calibrate/{device_id}?bar=4 grava ponto de calibração com as últimas leituras (X-Admin-Token)
  DELETE /v1/calibrate/{device_id}       apaga a calibração do dispositivo (X-Admin-Token)
  GET    /v1/devices                     estado de todos os dispositivos (X-Admin-Token)
  GET    /v1/devices/{device_id}/frame   último JPEG recebido (X-Admin-Token)
  GET    /healthz

Configuração (env)
  GATEWAY_DEVICES      caminho do devices.yaml (default gateway/devices.yaml)
  GATEWAY_DATA_DIR     pasta de estado: frames e calibração (default gateway/data)
  GATEWAY_ADMIN_TOKEN  token de administração (obrigatório para endpoints de admin)
  PUBLISH_MODE         none | local | pubsub   (default none)
  LOCAL_CLOUD_URL      Cloud Router local (PUBLISH_MODE=local), default http://localhost:8080
  TOPIC_ID / GOOGLE_CLOUD_PROJECT  para PUBLISH_MODE=pubsub
  COSMOS_URL, MODEL_ID  backends
"""
import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import statistics
import sys
import threading
import time
import urllib.request
from collections import deque

import yaml
from fastapi import FastAPI, Header, HTTPException, Request, Response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "edge"))

import cosmos_backend  # noqa: E402
from gauge_schema import GaugeReading  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s")
logger = logging.getLogger("GaugeGateway")

MAX_IMAGE_BYTES = 2 * 1024 * 1024
HISTORY = 20          # leituras guardadas por dispositivo (mediana e calibração)
CALIB_SAMPLES = 5     # leituras usadas para gravar um ponto de calibração
CALIB_MAX_AGE_S = 120 # só usa leituras recentes para calibrar
CALIB_MAX_SPREAD_DEG = 8.0  # recusa calibração se a agulha "pulou" entre as amostras
SAVE_FRAMES = int(os.getenv("GATEWAY_SAVE_FRAMES", "0"))  # guarda os N últimos frames por device (diagnóstico)


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


class DeviceState:
    def __init__(self):
        self.lock = threading.Lock()
        self.history = deque(maxlen=HISTORY)   # (t, bar, tip_deg|None)
        self.last = None
        self.last_frame = None
        self.count = 0


class Gateway:
    def __init__(self, devices_path=None, data_dir=None, readers=None, publisher=None):
        self.devices_path = devices_path or os.getenv("GATEWAY_DEVICES", os.path.join(ROOT, "gateway", "devices.yaml"))
        self.data_dir = data_dir or os.getenv("GATEWAY_DATA_DIR", os.path.join(ROOT, "gateway", "data"))
        os.makedirs(self.data_dir, exist_ok=True)
        self.calib_path = os.path.join(self.data_dir, "calibration.json")
        self.devices = self._load_devices()
        self.calibration = self._load_calibration()
        self.states = {d: DeviceState() for d in self.devices}
        self.readers = readers or {}          # backend -> callable(image_bytes, calib) -> (reading, tip_deg)
        self.publisher = publisher or make_publisher()
        self.admin_hash = sha256(os.environ["GATEWAY_ADMIN_TOKEN"]) if os.getenv("GATEWAY_ADMIN_TOKEN") else None
        self._calib_lock = threading.Lock()

    # ---------------- config / estado
    def _load_devices(self):
        if not os.path.exists(self.devices_path):
            raise RuntimeError(f"Arquivo de dispositivos não encontrado: {self.devices_path} (veja devices.example.yaml)")
        with open(self.devices_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        devs = data.get("devices", {})
        for dev_id, cfg in devs.items():
            if "token_sha256" not in cfg:
                raise RuntimeError(f"Dispositivo {dev_id} sem token_sha256")
            cfg.setdefault("backend", "cosmos")
        logger.info(f"{len(devs)} dispositivo(s) carregado(s) de {self.devices_path}")
        return devs

    def _load_calibration(self):
        if os.path.exists(self.calib_path):
            with open(self.calib_path, encoding="utf-8") as f:
                return {d: {float(k): float(v) for k, v in pts.items()} for d, pts in json.load(f).items()}
        return {}

    def _save_calibration(self):
        tmp = self.calib_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({d: {str(k): v for k, v in sorted(p.items())} for d, p in self.calibration.items()}, f, indent=2)
        os.replace(tmp, self.calib_path)

    def calib_string(self, device_id):
        pts = self.calibration.get(device_id, {})
        if len(pts) >= 2:
            return ",".join(f"{deg}:{bar}" for bar, deg in sorted(pts.items()))
        return self.devices[device_id].get("calib")   # calibração fixa do YAML (ou None = padrão)

    # ---------------- auth
    def check_device(self, device_id, token):
        cfg = self.devices.get(device_id)
        token = (token or "").strip()   # tolera espaço/quebra de linha copiados junto
        if cfg is None or not token or not hmac.compare_digest(sha256(token), cfg["token_sha256"]):
            # nunca registra o token; só o tamanho, para diagnóstico de digitação
            logger.warning(f"401 {device_id}: dispositivo {'conhecido' if cfg else 'desconhecido'}, "
                           f"token recebido com {len(token)} caracteres")
            raise HTTPException(401, "dispositivo ou token inválido")
        return cfg

    def check_admin(self, token):
        if not self.admin_hash or not token or not hmac.compare_digest(sha256(token), self.admin_hash):
            raise HTTPException(401, "token de administração inválido")

    # ---------------- leitura
    def reader(self, backend):
        if backend not in self.readers:
            self.readers[backend] = make_reader(backend)
        return self.readers[backend]

    def ingest(self, device_id, image_bytes):
        cfg = self.devices[device_id]
        st = self.states[device_id]
        t0 = time.perf_counter()
        reading, tip_deg = self.reader(cfg["backend"])(image_bytes, self.calib_string(device_id))
        reading = GaugeReading.model_validate(reading).model_dump()
        dt = time.perf_counter() - t0
        now = time.time()
        with st.lock:
            st.history.append((now, reading["data_bar"]["valor"], tip_deg))
            window = [b for _, b, _ in list(st.history)[-int(cfg.get("median", 5)):]]
            st.count += 1
            st.last_frame = image_bytes
            if SAVE_FRAMES:
                self._save_frame(device_id, image_bytes, reading["data_bar"]["valor"], tip_deg)
            smooth = round(statistics.median(window), 2)
            st.last = {
                "hora": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "bar": reading["data_bar"]["valor"], "psi": reading["data_psi"]["valor"],
                "bar_mediana": smooth, "psi_mediana": round(smooth * cosmos_backend.BAR_TO_PSI, 1),
                "confianca": reading["confianca_leitura"], "alerta_visibilidade": reading["alerta_visibilidade"],
                "tip_deg": tip_deg, "latencia_s": round(dt, 2), "backend": cfg["backend"],
            }
        payload = {
            "device_id": device_id,
            "timestamp": st.last["hora"],
            "location": cfg.get("location"),
            "telemetry": reading,
        }
        try:
            self.publisher(payload)
        except Exception as e:   # publicação não pode derrubar a leitura do dispositivo
            logger.error(f"Falha ao publicar {device_id}: {e}")
        logger.info(f"{device_id}: {st.last['bar']} bar (mediana {smooth}) em {dt:.2f}s via {cfg['backend']}")
        return {"device_id": device_id, **st.last, "raciocinio": reading["raciocinio_geometrico"]}

    def _save_frame(self, device_id, image_bytes, bar, tip_deg):
        d = os.path.join(self.data_dir, "frames", device_id)
        os.makedirs(d, exist_ok=True)
        name = time.strftime("%Y%m%d_%H%M%S") + f"_{bar:.2f}bar_{'na' if tip_deg is None else int(tip_deg)}deg.jpg"
        with open(os.path.join(d, name), "wb") as f:
            f.write(image_bytes)
        files = sorted(os.listdir(d))
        for old in files[:-SAVE_FRAMES]:
            os.remove(os.path.join(d, old))

    def calibrate(self, device_id, bar):
        st = self.states[device_id]
        now = time.time()
        with st.lock:
            recent = [deg for t, _, deg in st.history if deg is not None and now - t <= CALIB_MAX_AGE_S][-CALIB_SAMPLES:]
        if len(recent) < 3:
            raise HTTPException(409, f"poucas leituras recentes com ângulo ({len(recent)}); aguarde o dispositivo enviar mais imagens")
        ref = recent[0]
        unwrapped = [ref + ((x - ref + 180) % 360 - 180) for x in recent]
        deg = round(statistics.median(unwrapped) % 360, 1)
        spread = round(max(unwrapped) - min(unwrapped), 1)
        if spread > CALIB_MAX_SPREAD_DEG:
            raise HTTPException(409, f"leituras instáveis (dispersão {spread}° > {CALIB_MAX_SPREAD_DEG}°): "
                                     f"ângulos {[round(x % 360) for x in unwrapped]}; estabilize a pressão/câmera e tente de novo")
        with self._calib_lock:
            self.calibration.setdefault(device_id, {})[float(bar)] = deg
            self._save_calibration()
        return {"device_id": device_id, "bar": bar, "tip_deg": deg, "dispersao_deg": spread,
                "amostras": len(recent), "pontos": self.calibration[device_id]}


# ---------------- backends
def make_reader(backend):
    if backend == "cosmos":
        client = cosmos_backend.CosmosClient()

        def read(image_bytes, calib):
            reading, dbg = cosmos_backend.read_gauge(image_bytes, client=client, calib=calib, debug=True)
            return reading, dbg["needle"]["tip_deg"]
        return read
    if backend == "gemini":
        import gemini_backend
        client = gemini_backend.make_client(os.getenv("GOOGLE_CLOUD_PROJECT"))
        model_id = os.getenv("MODEL_ID", "gemini-3.6-flash")

        def read(image_bytes, calib):
            return gemini_backend.read_gauge(image_bytes, client, model_id), None
        return read
    raise RuntimeError(f"backend desconhecido: {backend}")


# ---------------- publicação
def make_publisher():
    mode = os.getenv("PUBLISH_MODE", "none").lower()
    if mode == "none":
        return lambda payload: None
    if mode == "local":
        url = os.getenv("LOCAL_CLOUD_URL", "http://localhost:8080")

        def pub_local(payload):
            data = base64.b64encode(json.dumps(payload).encode()).decode()
            req = urllib.request.Request(url, data=json.dumps({"message": {"data": data}}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3).read()
        return pub_local
    if mode == "pubsub":
        from google.cloud import pubsub_v1
        publisher = pubsub_v1.PublisherClient()
        topic = publisher.topic_path(os.getenv("GOOGLE_CLOUD_PROJECT"), os.environ["TOPIC_ID"])
        return lambda payload: publisher.publish(topic, json.dumps(payload).encode()).result(timeout=10)
    raise RuntimeError(f"PUBLISH_MODE inválido: {mode}")


# ---------------- FastAPI
def create_app(gateway=None):
    app = FastAPI(title="Gauge Gateway", version="1.0")
    app.state.gw = gateway

    def gw():
        if app.state.gw is None:
            app.state.gw = Gateway()
        return app.state.gw

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "devices": len(gw().devices)}

    @app.post("/v1/ingest/{device_id}")
    async def ingest(device_id: str, request: Request, x_device_token: str = Header(default=None)):
        g = gw()
        g.check_device(device_id, x_device_token)
        body = await request.body()
        if not body or len(body) > MAX_IMAGE_BYTES:
            raise HTTPException(413 if body else 400, "imagem ausente ou maior que 2 MB")
        if body[:2] != b"\xff\xd8":
            raise HTTPException(415, "envie um JPEG (Content-Type: image/jpeg)")
        try:
            # a inferência é bloqueante: roda fora do event loop
            import anyio
            return await anyio.to_thread.run_sync(g.ingest, device_id, body)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Erro processando {device_id}")
            raise HTTPException(502, f"falha na análise: {e}")

    @app.post("/v1/calibrate/{device_id}")
    def calibrate(device_id: str, bar: float, x_admin_token: str = Header(default=None)):
        g = gw()
        g.check_admin(x_admin_token)
        if device_id not in g.devices:
            raise HTTPException(404, "dispositivo desconhecido")
        return g.calibrate(device_id, bar)

    @app.delete("/v1/calibrate/{device_id}")
    def reset_calibration(device_id: str, x_admin_token: str = Header(default=None)):
        g = gw()
        g.check_admin(x_admin_token)
        g.calibration.pop(device_id, None)
        g._save_calibration()
        return {"device_id": device_id, "pontos": {}}

    @app.get("/v1/devices")
    def devices(x_admin_token: str = Header(default=None)):
        g = gw()
        g.check_admin(x_admin_token)
        return {d: {"location": c.get("location"), "backend": c["backend"], "leituras": g.states[d].count,
                    "calibracao": g.calibration.get(d, {}), "ultima": g.states[d].last}
                for d, c in g.devices.items()}

    @app.get("/v1/devices/{device_id}/frame")
    def frame(device_id: str, x_admin_token: str = Header(default=None)):
        g = gw()
        g.check_admin(x_admin_token)
        st = g.states.get(device_id)
        if not st or not st.last_frame:
            raise HTTPException(404, "sem frame")
        return Response(st.last_frame, media_type="image/jpeg")

    return app


app = create_app()
