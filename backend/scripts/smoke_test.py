"""End-to-end functional test of the LIVE system (backend on :8000).

Covers the happy path and every failure case in the demo brief:
  happy  : register -> login -> upload+GPS -> diagnosis -> DB -> hotspots -> history
  failure: invalid image, missing/partial/out-of-range GPS, oversized file,
           wrong content type, unauthenticated calls, low-confidence advice

Run from ``backend\\`` (Windows venv):  ..\\venv\\Scripts\\python.exe scripts\\smoke_test.py
Exit code 0 = all passed.
"""
from __future__ import annotations

import io
import sys
import time
import uuid

import httpx
from PIL import Image, ImageDraw

BASE = "http://127.0.0.1:8000"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def make_jpeg(w=640, h=480, colour=(34, 139, 34), quality=90) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def make_leafy_jpeg(seed: int) -> bytes:
    """A slightly structured green image so classes aren't all identical."""
    import random

    random.seed(seed)
    img = Image.new("RGB", (640, 480), (30 + seed % 40, 110 + seed % 60, 30))
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = random.randint(0, 640), random.randint(0, 480)
        r = random.randint(4, 40)
        c = (random.randint(20, 90), random.randint(100, 200), random.randint(20, 90))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60.0)

    print("\n=== 0. Health / classifier identity ===")
    r = c.get("/health")
    check("GET /health -> 200", r.status_code == 200, r.text)
    h = r.json()
    check("classifier is onnx (not mock)", h.get("classifier") == "onnx", str(h))

    # ---------------- auth ----------------
    print("\n=== 1. Register / login ===")
    phone = f"+2567{uuid.uuid4().int % 10_000_000:07d}"
    reg_payload = {
        "full_name": "Demo Evaluator",
        "phone": phone,
        "password": "secret123",
        "role": "farmer",
    }
    r = c.post("/api/v1/auth/register", json=reg_payload)
    check("POST /auth/register -> 201", r.status_code == 201, r.text)
    tok = r.json().get("access_token", "")
    check("register returns JWT", bool(tok))
    H = {"Authorization": f"Bearer {tok}"}

    r = c.post("/api/v1/auth/register", json=reg_payload)
    check("duplicate register -> 409", r.status_code == 409, r.text)

    r = c.post("/api/v1/auth/login", json={"identifier": phone, "password": "secret123"})
    check("POST /auth/login -> 200", r.status_code == 200, r.text)
    r = c.post("/api/v1/auth/login", json={"identifier": phone, "password": "nope"})
    check("wrong password -> 401", r.status_code == 401, r.text)
    tok = c.post("/api/v1/auth/login", json={"identifier": phone, "password": "secret123"}).json()[
        "access_token"
    ]
    H = {"Authorization": f"Bearer {tok}"}

    # ---------------- happy path ----------------
    print("\n=== 2. Full diagnosis flow (upload + GPS) ===")
    img = make_leafy_jpeg(7)
    t0 = time.perf_counter()
    r = c.post(
        "/diagnose",
        headers=H,
        files={"file": ("leaf.jpg", img, "image/jpeg")},
        data={"latitude": "0.3533", "longitude": "32.7553"},
    )
    e2e_ms = (time.perf_counter() - t0) * 1000
    check("POST /diagnose -> 200", r.status_code == 200, r.text)
    body = r.json()
    check(
        "response has all 10 fields",
        set(body)
        == {
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
        },
        str(sorted(body)),
    )
    check("label in Healthy/CMD/CBSD", body.get("label") in ("Healthy", "CMD", "CBSD"), str(body.get("label")))
    check("confidence in [0,1]", 0.0 <= body.get("confidence", -1) <= 1.0)
    check("advice is non-empty", bool(body.get("advice")))
    check("probabilities sum ~1", abs(sum(body["all_probabilities"].values()) - 1.0) < 0.01)
    check("GPS echoed", body["latitude"] == 0.3533 and body["longitude"] == 32.7553)
    check("diagnosis_id present", bool(body.get("diagnosis_id")))
    check("model_version is onnx", "onnx" in body.get("model_version", ""), body.get("model_version", ""))
    did = body["diagnosis_id"]
    print(f"    E2E latency (1st, cold-ish): {e2e_ms:.0f} ms | label={body['label']} conf={body['confidence']:.3f}")

    # ---------------- DB persistence ----------------
    print("\n=== 3. Saved to database / history ===")
    r = c.get("/api/v1/history", headers=H)
    check("GET /api/v1/history -> 200", r.status_code == 200, r.text)
    page = r.json()
    check("history total >= 1", page["total"] >= 1, str(page["total"]))
    check("new diagnosis in history", any(i["diagnosis_id"] == did for i in page["items"]))
    r = c.get("/api/v1/diagnoses", headers=H)
    check("GET /api/v1/diagnoses -> 200", r.status_code == 200, r.text)

    # ---------------- hotspots / map ----------------
    print("\n=== 4. Hotspots / map ===")
    r = c.get("/api/v1/hotspots", headers=H)
    check("GET /api/v1/hotspots (auth) -> 200", r.status_code == 200, r.text)
    fc = r.json()
    check("hotspots is FeatureCollection", fc.get("type") == "FeatureCollection")
    check("map has >= 1 cluster", len(fc.get("features", [])) >= 1, f"{len(fc.get('features', []))} features")
    r = c.get("/api/v1/hotspots")
    check("hotspots WITHOUT token -> 401", r.status_code == 401, r.text)
    r = c.get("/api/v1/clusters/geojson")
    check("public clusters/geojson -> 200", r.status_code == 200, r.text)

    # ---------------- failure cases ----------------
    print("\n=== 5. Failure cases ===")
    # invalid image
    r = c.post("/diagnose", headers=H, files={"file": ("bad.jpg", b"not an image at all", "image/jpeg")})
    check("invalid image bytes -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
    r = c.post("/diagnose", headers=H, files={"file": ("empty.jpg", b"", "image/jpeg")})
    check("empty file -> 422", r.status_code == 422, r.text[:120])

    # GPS
    r = c.post("/diagnose", headers=H, files={"file": ("l.jpg", img, "image/jpeg")}, data={"latitude": "0.35"})
    check("partial GPS -> 422", r.status_code == 422, r.text[:120])
    r = c.post(
        "/diagnose",
        headers=H,
        files={"file": ("l.jpg", img, "image/jpeg")},
        data={"latitude": "95", "longitude": "32"},
    )
    check("out-of-range GPS -> 422", r.status_code == 422, r.text[:120])
    r = c.post("/diagnose", headers=H, files={"file": ("l.jpg", img, "image/jpeg")})
    check("no GPS accepted (optional)", r.status_code == 200, r.text[:150])

    # oversized / wrong content type
    big = b"x" * (9 * 1024 * 1024)
    r = c.post("/diagnose", headers=H, files={"file": ("big.jpg", big, "image/jpeg")})
    check("oversized -> 413", r.status_code == 413, r.text[:120])
    r = c.post("/diagnose", headers=H, files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")})
    check("wrong content type -> 415", r.status_code == 415, r.text[:120])

    # auth
    r = c.post("/diagnose", files={"file": ("l.jpg", img, "image/jpeg")})
    check("/diagnose without token -> 401", r.status_code == 401, r.text[:120])
    r = c.get("/api/v1/history")
    check("/history without token -> 401", r.status_code == 401, r.text[:120])

    # ---------------- low-confidence advice ----------------
    print("\n=== 6. Low-confidence advice softening ===")
    # Find a colour that the model is unsure about by scanning a few.
    low_conf_seen = False
    for seed in range(1, 25):
        b = make_leafy_jpeg(seed)
        rr = c.post(
            "/diagnose",
            headers=H,
            files={"file": (f"s{seed}.jpg", b, "image/jpeg")},
        )
        if rr.status_code != 200:
            continue
        bb = rr.json()
        if bb["confidence"] < 0.60:
            low_conf_seen = True
            check(
                "low conf (<0.60) advice is softened",
                any(w in bb["advice"].lower() for w in ("low confidence", "preliminary", "retake", "not confident")),
                bb["advice"][:140],
            )
            break
    if not low_conf_seen:
        # Deterministic: call risk engine directly to prove softening works.
        from app.services.advice import build_advice  # type: ignore

        soft = build_advice("CMD", 0.55)
        check(
            "low-conf advice softened (unit-level)",
            "Low confidence" in soft and "preliminary" in soft,
            soft[:140],
        )

    # ---------------- latency sample ----------------
    print("\n=== 7. Latency (5 warm runs) ===")
    times = []
    for i in range(5):
        b = make_leafy_jpeg(100 + i)
        t0 = time.perf_counter()
        rr = c.post("/diagnose", headers=H, files={"file": (f"w{i}.jpg", b, "image/jpeg")})
        times.append((time.perf_counter() - t0) * 1000)
        if rr.status_code != 200:
            check("warm latency run succeeded", False, rr.text[:120])
            break
    else:
        check("5 warm latency runs all 200", True)
    avg = sum(times) / len(times)
    print(f"    min={min(times):.0f} ms  avg={avg:.0f} ms  max={max(times):.0f} ms  (n={len(times)})")

    print("\n" + "=" * 60)
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failed checks:")
        for f in FAIL:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
