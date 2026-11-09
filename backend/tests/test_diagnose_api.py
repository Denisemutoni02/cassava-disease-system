"""Unit tests for the diagnosis endpoint (POST /api/v1/diagnoses)."""

import io

import numpy as np
import pytest
from PIL import Image


def _jpeg(width=224, height=224, colour=(34, 139, 34)) -> tuple[bytes, str]:
    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue(), "image/jpeg"


class TestDiagnoseEndpoint:
    def test_requires_authentication(self, client):
        data, ctype = _jpeg()
        r = client.post(
            "/api/v1/diagnoses",
            files={"file": ("leaf.jpg", data, ctype)},
        )
        assert r.status_code == 401

    def test_happy_path_returns_label_confidence_advice(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "0.3533", "longitude": "32.7553"},
        )
        assert r.status_code == 201, r.text
        body = r.json()

        diag = body["diagnosis"]
        assert diag["disease_label"] in ("CMD", "CBSD", "Healthy", "Uncertain")
        assert 0.0 <= diag["confidence_score"] <= 1.0
        assert diag["advice"] is not None
        assert diag["advice"]["severity_level"] in ("Low", "Moderate", "High")
        assert diag["advice"]["advice_text"]
        assert diag["latitude"] == pytest.approx(0.3533, abs=1e-4)
        assert body["model_version"].startswith("mock")

    def test_invalid_file_type_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )
        assert r.status_code == 422
        assert "Unsupported file type" in r.json()["detail"]

    def test_corrupt_image_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        junk = b"\xff\xd8\xff" + b"\x00" * 4096  # fake JPEG header + junk
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("leaf.jpg", junk, "image/jpeg")},
        )
        assert r.status_code == 422

    def test_low_resolution_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        # Noisy image so the JPEG exceeds the 1 KB minimum-size guard
        rng = np.random.default_rng(0)
        arr = rng.integers(0, 255, size=(32, 32, 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=100)
        data = buf.getvalue()
        if len(data) < 1024:  # pad to pass the size guard, still 32×32
            data = data + b"\x00" * (1024 - len(data) + 1)
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("tiny.jpg", data, "image/jpeg")},
        )
        assert r.status_code == 422
        assert "resolution" in r.json()["detail"].lower() or "decoded" in r.json()["detail"].lower()

    def test_invalid_latitude_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "999", "longitude": "32.7"},
        )
        assert r.status_code == 422

    def test_half_gps_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/api/v1/diagnoses",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "0.35"},
        )
        assert r.status_code == 422

    def test_history_lists_own_diagnoses(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        for _ in range(2):
            r = client.post(
                "/api/v1/diagnoses",
                headers=headers,
                files={"file": ("leaf.jpg", data, ctype)},
            )
            assert r.status_code == 201

        r = client.get("/api/v1/diagnoses", headers=headers)
        assert r.status_code == 200
        page = r.json()
        assert page["total"] == 2
        assert len(page["items"]) == 2

    def test_same_image_same_mock_result(self, client, register_and_login):
        """Mock classifier is deterministic for identical bytes."""
        headers, _ = register_and_login()
        data, ctype = _jpeg(colour=(200, 50, 50))
        r1 = client.post(
            "/api/v1/diagnoses", headers=headers, files={"file": ("a.jpg", data, ctype)}
        )
        r2 = client.post(
            "/api/v1/diagnoses", headers=headers, files={"file": ("b.jpg", data, ctype)}
        )
        assert r1.json()["diagnosis"]["disease_label"] == r2.json()["diagnosis"]["disease_label"]
        assert (
            r1.json()["diagnosis"]["confidence_score"]
            == r2.json()["diagnosis"]["confidence_score"]
        )
