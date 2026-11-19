"""Simula um dispositivo IoT enviando fotos ao gateway (mesmo protocolo do firmware ESP32).

Uso: python gateway/simulate_device.py <device_id> <token> foto1.jpg [foto2.jpg ...] [--url http://127.0.0.1:8090] [--interval 1]
"""
import argparse
import json
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("device_id")
ap.add_argument("token")
ap.add_argument("images", nargs="+")
ap.add_argument("--url", default="http://127.0.0.1:8090")
ap.add_argument("--interval", type=float, default=0)
a = ap.parse_args()

for path in a.images:
    with open(path, "rb") as f:
        body = f.read()
    req = urllib.request.Request(f"{a.url}/v1/ingest/{a.device_id}", data=body, method="POST",
                                 headers={"Content-Type": "image/jpeg", "X-Device-Token": a.token})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
        print(f"{path}: {out['bar']} bar | {out['psi']} psi | mediana {out['bar_mediana']} | "
              f"conf {out['confianca']} | {time.perf_counter() - t0:.2f}s")
    except urllib.error.HTTPError as e:
        print(f"{path}: HTTP {e.code} {e.read().decode(errors='replace')}")
    time.sleep(a.interval)
