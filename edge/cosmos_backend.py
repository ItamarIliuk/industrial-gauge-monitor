"""Backend local de leitura de manômetro com NVIDIA Cosmos3 (NIM) + geometria da agulha.

Alternativa ao Gemini (Vertex AI): roda 100% na borda (ex.: RTX 4090), sem enviar imagem para a nuvem.

Pipeline:
  1. Cosmos3 Edge Reasoner localiza o mostrador (bbox_2d normalizado 0-1000) -> recorte quadrado.
  2. Geometria: a partir do pivô, mede o trecho escuro contínuo em cada direção. A PONTA FINA
     é o lado que vai mais longe; o contrapeso (curto e grosso) é ignorado.
  3. Ângulo -> bar por interpolação entre marcas impressas do mostrador (calibração).
  4. Devolve o mesmo esquema do backend Gemini (GaugeReading).

Observação: perguntar o valor direto ao Cosmos3 Edge NÃO funciona bem (ele segue o contrapeso,
que é mais saliente); por isso o VLM faz percepção (onde está o instrumento) e a geometria faz a medição.

Variáveis de ambiente:
  COSMOS_URL         (default http://localhost:8000)
  COSMOS_TIMEOUT_S   (default 30)
  GAUGE_CALIB        (default: manômetro STEELS 0-16 bar / 0-250 psi)
  GAUGE_ZERO_BAND    (default 0.6 bar: abaixo disso = agulha no pino de batente = 0)
  GAUGE_MAX_BAR      (default 17.0)
"""
import base64
import json
import logging
import math
import os
import re
import urllib.request

import cv2
import numpy as np

logger = logging.getLogger("CosmosBackend")

BAR_TO_PSI = 14.5038
DEFAULT_CALIB = "225:0,271.5:3.45,346.4:8,411.8:12,477:16"

PROMPT_BBOX = ("Locate the round dial face of the analog pressure gauge in this image. "
               'Return ONLY JSON: {"bbox_2d": [x1, y1, x2, y2]}')


# ---------------------------------------------------------------- calibração
def parse_calib(s):
    """'225:0,271.5:3.45,...' -> [(graus, bar), ...] com graus 'desenrolados' a partir do primeiro."""
    pts = []
    for item in s.split(","):
        d, b = item.split(":")
        pts.append((float(d), float(b)))
    base = pts[0][0]
    return sorted(((d - base) % 360 + base, b) for d, b in pts)


def deg_to_bar(deg, pts):
    """Interpolação linear por partes entre marcas do mostrador (extrapola nas pontas)."""
    base = pts[0][0]
    d = (deg - base) % 360 + base
    if d > pts[-1][0] + (360 - (pts[-1][0] - base)) / 2:  # zona morta: mais perto do 0
        d -= 360
    for (d0, b0), (d1, b1) in zip(pts, pts[1:]):
        if d <= d1 or (d1, b1) == pts[-1]:
            return b0 + (d - d0) * (b1 - b0) / (d1 - d0)
    return pts[-1][1]


# ---------------------------------------------------------------- geometria
def _dark_mask(gray):
    # a agulha está entre os pixels mais escuros; o teto absoluto evita que, num mostrador
    # quase todo branco (percentil alto), o fundo inteiro vire "escuro"
    thr = np.percentile(gray, 12)
    return gray < min(max(thr, 40) + 25, 120)


def _run_lengths(dark, cx, cy, R, step_deg=1.0, r0=0.10, gap=3):
    angles = np.arange(0, 360, step_deg)
    runs = np.zeros_like(angles)
    h, w = dark.shape
    radii = np.arange(int(r0 * R), int(0.98 * R))
    for i, deg in enumerate(angles):
        t = math.radians(deg)
        dx, dy = math.sin(t), -math.cos(t)  # 0° = 12h, sentido horário
        miss, last = 0, radii[0]
        for r in radii:
            x, y = int(round(cx + dx * r)), int(round(cy + dy * r))
            if not (0 <= x < w and 0 <= y < h):
                break
            if dark[y, x] or dark[min(h - 1, y + 1), x] or dark[y, min(w - 1, x + 1)]:
                miss, last = 0, r
            else:
                miss += 1
                if miss > gap:
                    break
        runs[i] = last / R
    return angles, runs


def needle_angle(bgr, size=512, search=0.08, grid=5):
    """Ângulo da PONTA FINA (graus, 12h = 0, horário) num recorte quadrado do mostrador."""
    gray = cv2.cvtColor(cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    dark = _dark_mask(gray.astype(np.float32))
    R = size / 2
    best = None
    for ox in np.linspace(-search, search, grid) * size:   # refina o pivô numa pequena grade
        for oy in np.linspace(-search, search, grid) * size:
            cx, cy = size / 2 + ox, size / 2 + oy
            _, runs = _run_lengths(dark, cx, cy, R, step_deg=2.0)
            if best is None or runs.max() > best[0]:
                best = (runs.max(), cx, cy)
    _, cx, cy = best
    ang, runs = _run_lengths(dark, cx, cy, R, step_deg=1.0)
    i_tip = int(np.argmax(runs))
    tip = float(ang[i_tip])
    opp = np.abs(((ang - (tip + 180)) + 180) % 360 - 180) <= 30
    i_tail = int(np.argmax(np.where(opp, runs, -1)))
    return {"tip_deg": tip, "tail_deg": float(ang[i_tail]),
            "tip_len": float(runs[i_tip]), "tail_len": float(runs[i_tail])}


def crop_from_bbox(bgr, bbox_norm, margin=0.12, min_side=768):
    """Recorte quadrado centrado no bbox (normalizado 0-1000), ampliado se pequeno."""
    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = [v / 1000.0 for v in bbox_norm]
    x1, x2 = sorted((x1 * w, x2 * w))
    y1, y2 = sorted((y1 * h, y2 * h))
    side = max(x2 - x1, y2 - y1) * (1 + 2 * margin)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bx1, by1 = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
    bx2, by2 = min(w, int(cx + side / 2)), min(h, int(cy + side / 2))
    crop = bgr[by1:by2, bx1:bx2]
    if crop.size and max(crop.shape[:2]) < min_side:
        s = min_side / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_LANCZOS4)
    return crop, (bx1, by1, bx2, by2)


# ---------------------------------------------------------------- Cosmos3 NIM
class CosmosClient:
    def __init__(self, url=None, timeout=None):
        self.url = (url or os.getenv("COSMOS_URL", "http://localhost:8000")).rstrip("/")
        self.timeout = float(timeout or os.getenv("COSMOS_TIMEOUT_S", "30"))
        self._model = None

    def _http(self, path, payload=None):
        req = urllib.request.Request(f"{self.url}{path}",
                                     data=json.dumps(payload).encode() if payload else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    @property
    def model(self):
        if self._model is None:
            self._model = self._http("/v1/models")["data"][0]["id"]
        return self._model

    def locate_dial(self, bgr):
        """Devolve bbox_2d normalizado (0-1000) do mostrador, ou None."""
        small = bgr
        if max(bgr.shape[:2]) > 1024:
            s = 1024 / max(bgr.shape[:2])
            small = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 92])
        b64 = base64.b64encode(buf.tobytes()).decode()
        resp = self._http("/v1/chat/completions", {
            "model": self.model, "max_tokens": 128, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": PROMPT_BBOX}]}]})
        text = resp["choices"][0]["message"].get("content") or ""
        for cand in reversed(re.findall(r"\{[^{}]*\}", text)):
            try:
                bbox = json.loads(cand).get("bbox_2d")
            except json.JSONDecodeError:
                continue
            if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
                return bbox
        return None


# ---------------------------------------------------------------- leitura
def _confidence(n, located):
    """Heurística: ponta bem mais longa que o contrapeso e longa o bastante = leitura confiável."""
    if n["tip_len"] < 0.35:
        return 0.3
    sep = min(1.0, max(0.0, (n["tip_len"] - n["tail_len"]) / 0.3))
    conf = 0.55 + 0.4 * sep
    return round(conf if located else conf * 0.8, 2)


def read_gauge(image_bytes, client=None, calib=None, zero_band=None, max_bar=None, debug=False):
    """Lê a pressão a partir de bytes JPEG/PNG. Devolve dict no esquema GaugeReading
    (com debug=True devolve também {box, needle, dial} para visualização)."""
    calib_pts = parse_calib(calib or os.getenv("GAUGE_CALIB", DEFAULT_CALIB))
    zero_band = float(zero_band if zero_band is not None else os.getenv("GAUGE_ZERO_BAND", "0.6"))
    max_bar = float(max_bar if max_bar is not None else os.getenv("GAUGE_MAX_BAR", "17.0"))
    client = client or CosmosClient()

    bgr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("Imagem inválida para o backend Cosmos.")

    bbox = client.locate_dial(bgr)
    located = bbox is not None
    dial, box = crop_from_bbox(bgr, bbox) if located else (bgr, None)

    n = needle_angle(dial)
    bar = max(0.0, deg_to_bar(n["tip_deg"], calib_pts))
    at_rest = bar < zero_band
    if at_rest:
        bar = 0.0
    bar = round(min(bar, max_bar), 2)
    psi = round(bar * BAR_TO_PSI, 1)

    conf = _confidence(n, located)
    if at_rest:
        conf = min(conf, 0.69)  # mesma regra do backend Gemini: leitura 0 reduz a confiança
    alerta = (not located) or n["tip_len"] < 0.35

    raciocinio = (
        f"Cosmos3 {'localizou o mostrador em ' + str(box) if located else 'NÃO localizou o mostrador (imagem inteira usada)'}. "
        f"Ponta fina em {n['tip_deg']:.0f}° (comprimento {n['tip_len']:.2f}R); "
        f"contrapeso em {n['tail_deg']:.0f}° ({n['tail_len']:.2f}R), ignorado. "
        + ("Agulha no pino de batente: 0 BAR." if at_rest else f"Interpolação pelas marcas do mostrador: {bar} BAR.")
    )
    result = {
        "raciocinio_geometrico": raciocinio,
        "data_bar": {"valor": bar, "unidade": "bar"},
        "data_psi": {"valor": psi, "unidade": "psi"},
        "confianca_leitura": conf,
        "alerta_visibilidade": bool(alerta),
    }
    if debug:
        return result, {"box": box, "needle": n, "dial": dial}
    return result
