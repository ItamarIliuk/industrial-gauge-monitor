"""Testes do Gateway IoT (sem GPU e sem nuvem: backend e publicação simulados)."""
import hashlib
import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway.main import Gateway, create_app  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
TOKEN, ADMIN = "tok-device-1", "tok-admin"


class FakeReader:
    """Simula o backend: devolve uma leitura fixa e um ângulo da ponta controlável."""
    def __init__(self):
        self.bar, self.tip = 4.0, 281.0
        self.calls = []

    def __call__(self, image_bytes, calib):
        self.calls.append(calib)
        return ({
            "raciocinio_geometrico": "teste",
            "data_bar": {"valor": self.bar, "unidade": "bar"},
            "data_psi": {"valor": round(self.bar * 14.5038, 1), "unidade": "psi"},
            "confianca_leitura": 0.95,
            "alerta_visibilidade": False,
        }, self.tip)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_ADMIN_TOKEN", ADMIN)
    devices = {"devices": {"dev1": {"token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
                                    "backend": "cosmos", "location": "Caldeira 1", "median": 3}}}
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(devices), encoding="utf-8")
    reader, published = FakeReader(), []
    gw = Gateway(devices_path=str(path), data_dir=str(tmp_path / "data"),
                 readers={"cosmos": reader}, publisher=published.append)
    return TestClient(create_app(gw)), gw, reader, published


def ingest(client, token=TOKEN, body=JPEG, dev="dev1"):
    return client.post(f"/v1/ingest/{dev}", content=body,
                       headers={"Content-Type": "image/jpeg", "X-Device-Token": token})


def test_ingest_returns_reading_and_publishes(ctx):
    client, gw, reader, published = ctx
    r = ingest(client)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["bar"] == 4.0 and out["psi"] == 58.0 and out["bar_mediana"] == 4.0
    assert published and published[0]["device_id"] == "dev1"
    assert published[0]["location"] == "Caldeira 1"
    assert published[0]["telemetry"]["data_bar"]["valor"] == 4.0   # mesmo formato do Edge Agent


def test_rejects_bad_token_unknown_device_and_non_jpeg(ctx):
    client, *_ = ctx
    assert ingest(client, token="errado").status_code == 401
    assert ingest(client, dev="nao-existe").status_code == 401
    assert ingest(client, body=b"PNG....").status_code == 415
    assert ingest(client, body=b"").status_code == 400


def test_median_smooths_outlier(ctx):
    client, gw, reader, _ = ctx
    for bar in (4.0, 4.0, 9.0):          # 9.0 é um salto isolado
        reader.bar = bar
        out = ingest(client).json()
    assert out["bar"] == 9.0 and out["bar_mediana"] == 4.0


def test_calibration_flow(ctx):
    client, gw, reader, _ = ctx
    admin = {"X-Admin-Token": ADMIN}
    assert client.post("/v1/calibrate/dev1?bar=4", headers=admin).status_code == 409   # sem leituras ainda
    for tip in (280.0, 281.0, 282.0):
        reader.tip = tip
        ingest(client)
    r = client.post("/v1/calibrate/dev1?bar=4", headers=admin)
    assert r.status_code == 200 and r.json()["tip_deg"] == 281.0
    reader.tip = 228.0
    ingest(client)
    # janela ainda mistura 4 bar e 0 bar: dispersão alta, calibração recusada
    assert client.post("/v1/calibrate/dev1?bar=0", headers=admin).status_code == 409
    for _ in range(5):
        ingest(client)
    assert client.post("/v1/calibrate/dev1?bar=0", headers=admin).status_code == 200
    ingest(client)
    assert reader.calls[-1] == "228.0:0.0,281.0:4.0"   # calibração passa a ser usada na leitura
    assert os.path.exists(gw.calib_path)              # e persiste em disco
    assert client.delete("/v1/calibrate/dev1", headers=admin).json()["pontos"] == {}


def test_admin_endpoints_require_token(ctx):
    client, *_ = ctx
    ingest(client)
    assert client.get("/v1/devices").status_code == 401
    r = client.get("/v1/devices", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 200 and r.json()["dev1"]["leituras"] == 1
    f = client.get("/v1/devices/dev1/frame", headers={"X-Admin-Token": ADMIN})
    assert f.status_code == 200 and f.content == JPEG


def test_publish_failure_does_not_break_ingest(ctx):
    client, gw, *_ = ctx
    def boom(payload):
        raise RuntimeError("pubsub fora do ar")
    gw.publisher = boom
    assert ingest(client).status_code == 200
