"""Gera um token para um novo dispositivo e imprime o trecho do devices.yaml.

Uso: python gateway/new_device.py manometro-caldeira-01 [--backend cosmos] [--location "Caldeira 1"]
O token aparece UMA vez: grave-o no dispositivo (portal de configuração do ESP32) e não o versione.
"""
import argparse
import hashlib
import secrets

ap = argparse.ArgumentParser()
ap.add_argument("device_id")
ap.add_argument("--backend", default="cosmos", choices=["cosmos", "gemini"])
ap.add_argument("--location", default="")
a = ap.parse_args()

token = secrets.token_hex(16)   # 32 caracteres 0-9a-f: fácil de digitar no portal do device
print(f"# Token do dispositivo (grave no ESP32, NÃO versione):\n#   {token}\n")
print(f"  {a.device_id}:")
print(f"    token_sha256: \"{hashlib.sha256(token.encode()).hexdigest()}\"")
print(f"    backend: {a.backend}")
if a.location:
    print(f"    location: \"{a.location}\"")
