"""Unit tests for auth endpoints and the classifier / risk / clustering services."""

import io

import numpy as np
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_register_and_me(self, client):
        r = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Auth Tester",
                "password": "secret123",
                "phone": "+256799999001",
                "role": "farmer",
            },
        )
        assert r.status_code == 201
        token = r.json()["access_token"]
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "farmer"

    def test_login_wrong_password(self, client):
        client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Login Tester",
                "password": "secret123",
                "phone": "+256799999002",
                "role": "farmer",
            },
        )
        r = client.post(
            "/api/v1/auth/login",
            json={"identifier": "+256799999002", "password": "wrong"},
        )
        assert r.status_code == 401

    def test_register_requires_contact(self, client):
        r = client.post(
            "/api/v1/auth/register",
            json={"full_name": "No Contact", "password": "secret123", "role": "farmer"},
        )
        assert r.status_code == 422

    def test_admin_endpoints_denied_for_farmer(self, client, register_and_login):
        headers, _ = register_and_login(role="farmer")
        r = client.get("/api/v1/admin/stats", headers=headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Classifier (mock mode)
# ---------------------------------------------------------------------------


class TestMockClassifier:
    def test_deterministic(self):
        from app.services.classifier import MockClassifier

        clf = MockClassifier()
        payload = b"fixed-image-bytes-for-testing"
        p1 = clf.predict(payload)
        p2 = clf.predict(payload)
        assert p1.label == p2.label
        assert p1.confidence == p2.confidence

    def test_label_domain(self):
        from app.services.classifier import CLASS_NAMES, MockClassifier

        clf = MockClassifier()
        for i in range(32):
            p = clf.predict(bytes([i]) * 512)
            assert p.label in CLASS_NAMES
            assert 0.0 <= p.confidence <= 1.0


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------


class TestRiskEngine:
    def test_confident_cmd(self):
        from app.services.risk_engine import RiskEngine

        r = RiskEngine().evaluate("CMD", 0.92, threshold=0.60)
        assert r.final_label == "CMD"
        assert r.severity_level == "Moderate"
        assert "whitefly" in r.advice_text.lower()

    def test_low_becomes_uncertain(self):
        from app.services.risk_engine import RiskEngine

        r = RiskEngine().evaluate("CBSD", 0.40, threshold=0.60)
        assert r.final_label == "Uncertain"
        assert r.is_confident is False
        assert "retake" in r.advice_text.lower()

    def test_healthy_low_severity(self):
        from app.services.risk_engine import RiskEngine

        r = RiskEngine().evaluate("Healthy", 0.88, threshold=0.60)
        assert r.final_label == "Healthy"
        assert r.severity_level == "Low"


# ---------------------------------------------------------------------------
# Clustering maths
# ---------------------------------------------------------------------------


class TestClustering:
    def test_haversine_zero_for_same_point(self):
        from app.services.clustering import haversine_km

        assert haversine_km(0.35, 32.75, 0.35, 32.75) == pytest.approx(0.0, abs=1e-6)

    def test_dbscan_finds_cluster(self):
        import uuid

        from app.services.clustering import run_dbscan

        # 5 points within ~300 m of Mukono + 1 isolated point 5 km away
        base_lat, base_lon = 0.3533, 32.7553
        points = []
        for i in range(5):
            points.append(
                (base_lat + i * 1e-4, base_lon + i * 1e-4, "CMD", uuid.uuid4())
            )
        points.append((0.40, 32.75, "CBSD", uuid.uuid4()))  # noise

        clusters = run_dbscan(points, eps_m=1000, min_samples=3)
        assert len(clusters) == 1
        c = clusters[0]
        assert c.member_count == 5
        assert c.dominant_disease == "CMD"
        assert c.risk_level == "Emerging"  # 5 members → Emerging

    def test_too_few_points_no_cluster(self):
        import uuid

        from app.services.clustering import run_dbscan

        points = [(0.35, 32.75, "CMD", uuid.uuid4()), (0.351, 32.751, "CMD", uuid.uuid4())]
        assert run_dbscan(points, eps_m=1000, min_samples=3) == []

    def test_risk_level_thresholds(self):
        from app.services.clustering import risk_level_for

        assert risk_level_for(3) == "Low"
        assert risk_level_for(5) == "Emerging"
        assert risk_level_for(12) == "High"


# ---------------------------------------------------------------------------
# Clusters API
# ---------------------------------------------------------------------------


class TestClustersAPI:
    def test_geojson_shape(self, client):
        r = client.get("/api/v1/clusters/geojson")
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "FeatureCollection"
        assert isinstance(body["features"], list)

    def test_recompute_requires_staff(self, client, register_and_login):
        headers, _ = register_and_login(role="farmer")
        r = client.post("/api/v1/clusters/recompute", headers=headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_reports_mock_mode(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["classifier"] == "mock"
        assert body["online_required"] is True
