"""Tests for GET /api/v1/history and GET /api/v1/hotspots (both JWT-protected)."""


class TestHistoryEndpoint:
    def test_requires_authentication(self, client):
        r = client.get("/api/v1/history")
        assert r.status_code == 401

    def test_empty_history_for_new_user(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.get("/api/v1/history", headers=headers)
        assert r.status_code == 200
        page = r.json()
        assert page["total"] == 0
        assert page["items"] == []

    def test_history_is_scoped_to_own_user(self, client, register_and_login):
        farmer_a, _ = register_and_login()
        farmer_b, _ = register_and_login()

        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (224, 224), (34, 139, 34))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        data = buf.getvalue()
        r = client.post(
            "/diagnose", headers=farmer_a, files={"file": ("leaf.jpg", data, "image/jpeg")}
        )
        assert r.status_code == 200

        assert client.get("/api/v1/history", headers=farmer_b).json()["total"] == 0
        assert client.get("/api/v1/history", headers=farmer_a).json()["total"] == 1


class TestHotspotsEndpoint:
    def test_requires_authentication(self, client):
        r = client.get("/api/v1/hotspots")
        assert r.status_code == 401

    def test_returns_valid_feature_collection(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.get("/api/v1/hotspots", headers=headers)
        assert r.status_code == 200
        fc = r.json()
        assert fc["type"] == "FeatureCollection"
        assert isinstance(fc["features"], list)
        for feature in fc["features"]:
            assert feature["type"] == "Feature"
            assert feature["geometry"]["type"] == "Point"
            assert "cluster_id" in feature["properties"]

    def test_disease_filter_param_accepted(self, client, register_and_login):
        headers, _ = register_and_login()
        for disease in ("CMD", "CBSD", "Healthy"):
            r = client.get(f"/api/v1/hotspots?disease={disease}", headers=headers)
            assert r.status_code == 200

    def test_invalid_disease_filter_rejected(self, client, register_and_login):
        headers, _ = register_and_login()
        r = client.get("/api/v1/hotspots?disease=Mosaic", headers=headers)
        assert r.status_code == 422
