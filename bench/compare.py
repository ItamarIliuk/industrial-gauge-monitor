"""Compara os backends Gemini (Vertex AI) e Cosmos3 (NIM local) nas mesmas fotos.

Usa exatamente o mesmo caminho de inferência do Edge Agent (GaugeAgent.process_inference),
sem câmera e sem publicar no Pub/Sub.

Uso:
  python bench/compare.py <pasta_fotos> [--backends cosmos,gemini] [--ref bench/reference_visual.csv] [--out bench/results.csv]

Requisitos:
  cosmos -> NIM do Cosmos3 rodando em COSMOS_URL (default http://localhost:8000)
  gemini -> credenciais GCP (GOOGLE_APPLICATION_CREDENTIALS ou gcloud ADC) e GOOGLE_CLOUD_PROJECT
"""
import argparse
import csv
import glob
import os
import statistics
import sys
import time
from unittest.mock import patch

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "edge"))


def make_agent(backend):
    os.environ.setdefault("TOPIC_ID", "bench-dummy")
    import app
    app.GAUGE_BACKEND = backend
    with patch.object(app.pubsub_v1, "PublisherClient"):   # sem Pub/Sub no benchmark
        return app.GaugeAgent()


def load_jpeg_bytes(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)                # aplica a orientação EXIF
    if img is None:
        raise RuntimeError(f"Não abriu {path}")
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


def load_ref(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["arquivo"]: float(r["bar_ref"]) for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--backends", default="cosmos,gemini")
    ap.add_argument("--ref", default=os.path.join(ROOT, "bench", "reference_visual.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "bench", "results.csv"))
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.folder, "*.jp*g")) + glob.glob(os.path.join(a.folder, "*.png")))
    ref = load_ref(a.ref)
    backends = [b.strip() for b in a.backends.split(",") if b.strip()]
    rows = []

    for backend in backends:
        try:
            agent = make_agent(backend)
        except Exception as e:
            print(f"[{backend}] não inicializou: {e}", file=sys.stderr)
            continue
        for path in files:
            name = os.path.basename(path)
            t0 = time.perf_counter()
            try:
                r = agent.process_inference(load_jpeg_bytes(path))
                err = None
            except Exception as e:
                r, err = None, str(e)
            dt = time.perf_counter() - t0
            bar = r["data_bar"]["valor"] if r else None
            rows.append({
                "backend": backend, "arquivo": name, "bar_ref": ref.get(name),
                "bar": bar, "psi": r["data_psi"]["valor"] if r else None,
                "erro_bar": round(bar - ref[name], 2) if (r and name in ref) else None,
                "confianca": r["confianca_leitura"] if r else None,
                "alerta": r["alerta_visibilidade"] if r else None,
                "latencia_s": round(dt, 2), "falha": err,
            })
            print(f"[{backend}] {name}: {bar} bar (ref {ref.get(name)}) em {dt:.2f}s" + (f"  ERRO: {err}" if err else ""))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["backend"])
        w.writeheader()
        w.writerows(rows)

    print("\n=== Resumo ===")
    for backend in backends:
        rs = [r for r in rows if r["backend"] == backend and r["erro_bar"] is not None]
        if not rs:
            continue
        mae = statistics.mean(abs(r["erro_bar"]) for r in rs)
        mae_p = [abs(r["erro_bar"]) for r in rs if r["bar_ref"] > 0]
        lat = statistics.median(r["latencia_s"] for r in rows if r["backend"] == backend)
        print(f"{backend:7s} | n={len(rs)} | MAE={mae:.2f} bar | MAE(com pressão)="
              f"{statistics.mean(mae_p):.2f} bar | max={max(abs(r['erro_bar']) for r in rs):.2f} | "
              f"latência mediana={lat:.2f}s")
    print(f"\nCSV: {a.out}")


if __name__ == "__main__":
    main()
