"""Testes do backend Cosmos3 (sem GPU: o cliente NIM é simulado)."""
import math
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "edge"))
import cosmos_backend as cb  # noqa: E402

CALIB = cb.parse_calib(cb.DEFAULT_CALIB)


def synthetic_gauge(tip_deg, size=600):
    """Mostrador branco com agulha: ponta fina e longa em tip_deg, contrapeso curto e grosso no lado oposto."""
    img = np.full((size, size, 3), 255, np.uint8)
    c = size // 2
    cv2.circle(img, (c, c), int(size * 0.47), (60, 60, 60), 4)          # aro
    for d in range(225, 225 + 271, 15):                                  # marcas da escala
        t = math.radians(d)
        p1 = (int(c + math.sin(t) * size * 0.40), int(c - math.cos(t) * size * 0.40))
        p2 = (int(c + math.sin(t) * size * 0.44), int(c - math.cos(t) * size * 0.44))
        cv2.line(img, p1, p2, (0, 0, 0), 3)

    def pt(deg, r):
        t = math.radians(deg)
        return int(c + math.sin(t) * r), int(c - math.cos(t) * r)

    cv2.line(img, (c, c), pt(tip_deg, size * 0.42), (0, 0, 0), 5)            # ponta fina e longa
    cv2.line(img, (c, c), pt(tip_deg + 180, size * 0.15), (0, 0, 0), 22)     # contrapeso curto e grosso
    cv2.circle(img, (c, c), 18, (0, 0, 0), -1)                               # pivô
    return img


class FakeClient:
    def __init__(self, bbox=(50, 50, 950, 950)):
        self.bbox = list(bbox) if bbox else None

    def locate_dial(self, bgr):
        return self.bbox


def jpeg(img):
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_calib_interpolates_printed_marks():
    assert cb.deg_to_bar(225, CALIB) == pytest.approx(0.0)
    assert cb.deg_to_bar(271.5, CALIB) == pytest.approx(3.45)
    assert cb.deg_to_bar(346.4, CALIB) == pytest.approx(8.0)
    assert cb.deg_to_bar(51.8, CALIB) == pytest.approx(12.0)      # 411.8 - 360
    assert cb.deg_to_bar(117, CALIB) == pytest.approx(16.0)       # 477 - 360


def test_dead_zone_maps_to_nearest_end():
    assert cb.deg_to_bar(200, CALIB) < 0          # logo antes do 0 -> negativo (vira 0 depois)
    assert cb.deg_to_bar(150, CALIB) > 16         # logo depois do 16 -> extrapola para cima


@pytest.mark.parametrize("tip_deg", [230, 270, 320, 20, 90])
def test_needle_angle_picks_thin_tip_not_counterweight(tip_deg):
    n = cb.needle_angle(synthetic_gauge(tip_deg))
    diff = abs((n["tip_deg"] - tip_deg + 180) % 360 - 180)
    assert diff <= 4, n
    assert n["tip_len"] > n["tail_len"]


def test_read_gauge_returns_gemini_schema():
    r = cb.read_gauge(jpeg(synthetic_gauge(271.5)), client=FakeClient())
    assert set(r) == {"raciocinio_geometrico", "data_bar", "data_psi", "confianca_leitura", "alerta_visibilidade"}
    assert r["data_bar"]["unidade"] == "bar" and r["data_psi"]["unidade"] == "psi"
    assert r["data_bar"]["valor"] == pytest.approx(3.45, abs=0.3)
    assert r["data_psi"]["valor"] == pytest.approx(r["data_bar"]["valor"] * cb.BAR_TO_PSI, abs=0.1)
    assert r["alerta_visibilidade"] is False
    assert 0.5 <= r["confianca_leitura"] <= 1.0


def test_read_gauge_zero_band_and_low_confidence():
    r = cb.read_gauge(jpeg(synthetic_gauge(228)), client=FakeClient())
    assert r["data_bar"]["valor"] == 0.0
    assert r["confianca_leitura"] < 0.70          # mesma regra do prompt Gemini para leitura 0


def test_read_gauge_flags_when_dial_not_found():
    r = cb.read_gauge(jpeg(synthetic_gauge(300)), client=FakeClient(bbox=None))
    assert r["alerta_visibilidade"] is True


def test_agent_uses_cosmos_backend(monkeypatch):
    from unittest.mock import patch
    monkeypatch.setenv("TOPIC_ID", "test-topic")
    import app
    monkeypatch.setattr(app, "GAUGE_BACKEND", "cosmos")
    with patch.object(app.pubsub_v1, "PublisherClient"):
        agent = app.GaugeAgent()
    agent.client = FakeClient()
    out = agent.process_inference(jpeg(synthetic_gauge(346.4)))
    assert out["data_bar"]["valor"] == pytest.approx(8.0, abs=0.4)


def test_invalid_backend_rejected(monkeypatch):
    from unittest.mock import patch
    monkeypatch.setenv("TOPIC_ID", "test-topic")
    import app
    monkeypatch.setattr(app, "GAUGE_BACKEND", "xpto")
    with patch.object(app.pubsub_v1, "PublisherClient"), pytest.raises(EnvironmentError):
        app.GaugeAgent()
