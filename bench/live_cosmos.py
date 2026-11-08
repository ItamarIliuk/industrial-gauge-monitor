r"""Leitura ao vivo: captura da câmera USB (Windows/DirectShow) -> Cosmos3 NIM -> pressão em bar/psi.

Não publica no Pub/Sub: serve para validar enquadramento e leitura em bancada.
Salva em debug_captures/: live_frame.jpg (frame bruto) e live_annotated.jpg (bbox + agulha + leitura).

Uso (PowerShell, na raiz do repo):
  .\.venv\Scripts\python.exe bench\live_cosmos.py [--camera 0] [--width 640 --height 480] [--loop 5]
"""
import argparse
import json
import math
import statistics
import os
import sys
import time

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "edge"))
import cosmos_backend as cb  # noqa: E402


def open_camera(index, width, height):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"Câmera {index} não abriu")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def grab(cap, warmup=30):
    frame = None
    for _ in range(warmup):            # descarta frames de auto-exposição / buffer antigo
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
        time.sleep(0.03)
    if frame is None or frame.max() <= 5:
        raise RuntimeError("Câmera não entregou frame válido")
    return frame


def annotate(frame, result, dbg):
    out = frame.copy()
    box = dbg["box"]
    n = dbg["needle"]
    if box:
        x1, y1, x2, y2 = box
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        # desenha a direção da ponta fina (vermelho) e do contrapeso (azul) a partir do centro do recorte
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        R = (x2 - x1) / 2
        for deg, ln, color in ((n["tip_deg"], n["tip_len"], (0, 0, 255)), (n["tail_deg"], n["tail_len"], (255, 0, 0))):
            t = math.radians(deg)
            p = (int(cx + math.sin(t) * ln * R), int(cy - math.cos(t) * ln * R))
            cv2.line(out, (int(cx), int(cy)), p, color, 3)
    txt = f"{result['data_bar']['valor']:.2f} bar | {result['data_psi']['valor']:.1f} psi | conf {result['confianca_leitura']:.2f}"
    cv2.rectangle(out, (0, 0), (out.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(out, txt, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=int(os.getenv("CAMERA_INDEX", "0")))
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--loop", type=float, default=0, help="segundos entre leituras (0 = uma leitura)")
    ap.add_argument("--count", type=int, default=0, help="número máximo de leituras no loop (0 = sem limite)")
    ap.add_argument("--keep", action="store_true", help="guarda cada frame anotado em debug_captures/loop/")
    ap.add_argument("--median", type=int, default=5, help="janela da mediana móvel (1 = sem suavização)")
    ap.add_argument("--calib-file", default=os.path.join(ROOT, "debug_captures", "calib_camera.json"),
                    help="pontos de calibração desta câmera (ângulo da ponta -> bar)")
    ap.add_argument("--calib-point", type=float, default=None,
                    help="modo calibração: pressão conhecida (bar) do patamar atual; grava a mediana do ângulo")
    a = ap.parse_args()

    os.makedirs(os.path.join(ROOT, "debug_captures"), exist_ok=True)
    points = {}
    if os.path.exists(a.calib_file):
        with open(a.calib_file, encoding="utf-8") as f:
            points = {float(k): float(v) for k, v in json.load(f).items()}
    calib = None
    if a.calib_point is None and len(points) >= 2:
        # ordena pela pressão; o parser desenrola os ângulos a partir do ponto de 0 bar
        calib = ",".join(f"{deg}:{bar}" for bar, deg in sorted(points.items()))
        print(f"Calibração da câmera ({a.calib_file}): {calib}")
    elif a.calib_point is None:
        print("Sem calibração da câmera: usando GAUGE_CALIB / padrão das fotos.")
    if a.calib_point is not None and not a.count:
        a.count, a.loop = 10, a.loop or 1.0
    angles, history = [], []
    client = cb.CosmosClient()
    cap = open_camera(a.camera, a.width, a.height)
    print(f"Câmera {a.camera}: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} | NIM {client.url}")
    loop_dir = os.path.join(ROOT, "debug_captures", "loop")
    if a.keep:
        os.makedirs(loop_dir, exist_ok=True)
    i = 0
    try:
        while True:
            i += 1
            frame = grab(cap, warmup=3 if i > 1 else 30)
            t0 = time.perf_counter()
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            result, dbg = cb.read_gauge(buf.tobytes(), client=client, calib=calib, debug=True)
            dt = time.perf_counter() - t0
            angles.append(dbg["needle"]["tip_deg"])
            history.append(result["data_bar"]["valor"])
            smooth = statistics.median(history[-max(1, a.median):])
            cv2.imwrite(os.path.join(ROOT, "debug_captures", "live_frame.jpg"), frame)
            cv2.imwrite(os.path.join(ROOT, "debug_captures", "live_annotated.jpg"), annotate(frame, result, dbg))
            cv2.imwrite(os.path.join(ROOT, "debug_captures", "live_dial.jpg"), dbg["dial"])
            if a.keep:
                cv2.imwrite(os.path.join(loop_dir, f"{i:04d}.jpg"), annotate(frame, result, dbg))
            print(json.dumps({"n": i, "hora": time.strftime("%H:%M:%S"), "latencia_s": round(dt, 2),
                              "tip_deg": dbg["needle"]["tip_deg"],
                              "bar_mediana": round(smooth, 2), "psi_mediana": round(smooth * cb.BAR_TO_PSI, 1),
                              **result}, ensure_ascii=False), flush=True)
            if a.loop <= 0 or (a.count and i >= a.count):
                break
            time.sleep(a.loop)
    finally:
        cap.release()

    if a.calib_point is not None:
        # mediana circular simples: desenrola em torno do primeiro ângulo antes de tirar a mediana
        ref = angles[0]
        unwrapped = [ref + ((x - ref + 180) % 360 - 180) for x in angles]
        deg = round(statistics.median(unwrapped) % 360, 1)
        spread = round(max(unwrapped) - min(unwrapped), 1)
        points[a.calib_point] = deg
        with open(a.calib_file, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in sorted(points.items())}, f, indent=2)
        print(f"PONTO DE CALIBRAÇÃO: {a.calib_point} bar -> {deg}° (dispersão {spread}° em {len(angles)} leituras)")
        print(f"Pontos atuais: {json.dumps(points)}  ->  {a.calib_file}")


if __name__ == "__main__":
    main()

