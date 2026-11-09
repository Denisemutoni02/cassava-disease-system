"""Tests for the integrated POST /diagnose endpoint (JWT, saves to DB).

``conftest.py`` sets ``FORCE_MOCK_MODEL=true``, so predictions here come from
the deterministic mock classifier — the tests therefore assert the contract
(status codes, schema shape, persistence, advice rules) rather than model
accuracy.
"""

import io

import pytest
from PIL import Image

from app.services.advice import build_advice


def _jpeg(width: int = 224, height: int = 224, colour=(34, 139, 34)) -> tuple[bytes, str]:
    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue(), "image/jpeg"


class TestDiagnoseEndpoint:
    def test_happy_path_with_gps(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "0.35", "longitude": "32.75"},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        # Exact documented response shape
        assert set(body) == {
            "label",
            "confidence",
            "advice",
            "all_probabilities",
            "latitude",
            "longitude",
            "diagnosis_id",
            "nearby_hotspots",
            "hotspot_message",
            "model_version",
        }
        assert body["label"] in ("Healthy", "CMD", "CBSD")
        assert 0.0 <= body["confidence"] <= 1.0
        assert body["advice"]
        assert set(body["all_probabilities"]) == {"Healthy", "CMD", "CBSD"}
        assert body["latitude"] == pytest.approx(0.35)
        assert body["longitude"] == pytest.approx(32.75)
        assert body["diagnosis_id"]  # persisted → UUID returned
        assert isinstance(body["nearby_hotspots"], int)
        assert body["model_version"]

    def test_happy_path_without_gps(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post("/diagnose", headers=headers, files={"file": ("leaf.jpg", data, ctype)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["latitude"] is None
        assert body["longitude"] is None
        assert body["hotspot_message"] is None
        # Confidence in response matches the reported class probability
        assert body["all_probabilities"][body["label"]] == pytest.approx(
            body["confidence"], abs=1e-3
        )

    def test_diagnosis_is_saved_and_listed_in_history(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "0.35", "longitude": "32.75"},
        )
        assert r.status_code == 200, r.text
        diagnosis_id = r.json()["diagnosis_id"]

        r = client.get("/api/v1/history", headers=headers)
        assert r.status_code == 200
        page = r.json()
        assert page["total"] == 1
        assert page["items"][0]["diagnosis_id"] == diagnosis_id
        assert page["items"][0]["disease_label"] in ("Healthy", "CMD", "CBSD")
        assert page["items"][0]["advice"]["advice_text"]

    def test_same_image_is_deterministic(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        first = client.post(
            "/diagnose", headers=headers, files={"file": ("a.jpg", data, ctype)}
        ).json()
        second = client.post(
            "/diagnose", headers=headers, files={"file": ("b.jpg", data, ctype)}
        ).json()
        assert first["label"] == second["label"]
        assert first["confidence"] == second["confidence"]

    def test_partial_gps_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": "0.35"},
        )
        assert r.status_code == 422
        assert "both latitude and longitude" in r.json()["detail"]

    @pytest.mark.parametrize(
        ("lat", "lon"),
        [("91", "0"), ("-91", "0"), ("0", "181"), ("0", "-181")],
    )
    def test_out_of_range_gps_rejected(self, client, register_and_login, lat, lon):
        headers, _ = register_and_login()
        data, ctype = _jpeg()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.jpg", data, ctype)},
            data={"latitude": lat, "longitude": lon},
        )
        assert r.status_code == 422

    def test_non_image_bytes_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.jpg", b"definitely not an image", "image/jpeg")},
        )
        assert r.status_code == 422
        assert "could not be decoded" in r.json()["detail"]

    def test_empty_file_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.post(
            "/diagnose", headers=headers, files={"file": ("leaf.jpg", b"", "image/jpeg")}
        )
        assert r.status_code == 422

    def test_unsupported_content_type_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.post(
            "/diagnose",
            headers=headers,
            files={"file": ("leaf.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 415

    def test_oversized_upload_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        # Size is checked before decoding, so padding valid bytes is enough
        big = b"x" * (9 * 1024 * 1024)
        r = client.post("/diagnose", headers=headers, files={"file": ("big.jpg", big, "image/jpeg")})
        assert r.status_code == 413

    def test_requires_authentication(self, client):
        """No Authorization header → 401; diagnosis must be logged in."""
        data, ctype = _jpeg()
        r = client.post("/diagnose", files={"file": ("leaf.jpg", data, ctype)})
        assert r.status_code == 401
        assert "log in" in r.json()["detail"].lower()

    def test_invalid_token_rejected(self, client):
        data, ctype = _jpeg()
        r = client.post(
            "/diagnose",
            headers={"Authorization": "Bearer not-a-real-token"},
            files={"file": ("leaf.jpg", data, ctype)},
        )
        assert r.status_code == 401


class TestAdviceRules:
    def test_healthy_message(self):
        advice = build_advice("Healthy", 0.95)
        assert "healthy" in advice.lower()
        assert "Avoid using this plant for cuttings" not in advice  # that is CMD advice
        assert "Low confidence" not in advice

    def test_cmd_message(self):
        advice = build_advice("CMD", 0.93)
        assert "Avoid using this plant for cuttings" in advice
        assert "MuZARDI extension officer" in advice

    def test_cbsd_message_warns_about_roots(self):
        advice = build_advice("CBSD", 0.93)
        assert "root" in advice.lower() or "tuber" in advice.lower()
        assert "MuZARDI extension officer" in advice

    def test_low_confidence_softens_tone(self):
        confident = build_advice("CMD", 0.93)
        unsure = build_advice("CMD", 0.55)
        assert unsure != confident
        assert "Low confidence (55%)" in unsure
        assert "preliminary" in unsure
        assert "Retake the photo" in unsure

    def test_threshold_boundary(self):
        assert "Low confidence" not in build_advice("CMD", 0.70)
        assert "Low confidence" in build_advice("CMD", 0.699)

    def test_unknown_label_falls_back(self):
        advice = build_advice("SomethingElse", 0.9)
        assert "could not classify" in advice
