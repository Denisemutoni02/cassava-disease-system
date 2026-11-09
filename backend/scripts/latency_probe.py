"""Live end-to-end latency probe: POST /diagnose over HTTP, N runs.

Reports min / median / p95 / max in ms — i.e. what a farmer actually waits
for (upload → JSON response), including auth, validation, DB write and
inference.  Requires the backend on :8000.
"""
from __future__ import annotations

import io
import statistics
import sys
import time
import uuid

import httpx
from PIL import Image, ImageDraw

BASE = "http://127.0.0.1:8000"
N = 20


def make_leaf(seed: int) -> bytes:
    import random

    random.seed(seed)
    img = Image.new("RGB", (1280, 960), (30 + seed % 40, 110 + seed % 60, 30))
    d = ImageDraw.Draw(img)
    for _ in range(80):
        x, y = random.randint(0, 1280), random.randint(0, 960)
        r = random.randint(6, 60)
        d.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=(random.randint(20, 90), random.randint(100, 200), random.randint(20, 90)),
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60.0)
    phone = f"+2567{uuid.uuid4().int % 10_000_000:07d}"
    r = c.post(
        "/api/v1/auth/register",
        json={"full_name": "Latency Probe", "phone": phone, "password": "secret123"},
    )
    if r.status_code != 201:
        print("register failed:", r.status_code, r.text)
        return 1
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 3 warm-ups (JIT/ORT warm-up, first-encode overhead)
    for i in range(3):
        c.post("/diagnose", headers=H, files={"file": (f"w{i}.jpg", make_leaf(i), "image/jpeg")})

    times: list[float] = []
    statuses: list[int] = []
    for i in range(N):
        payload = make_leaf(1000 + i)
        t0 = time.perf_counter()
        r = c.post(
            "/diagnose",
            headers=H,
            files={"file": (f"l{i}.jpg", payload, "image/jpeg")},
            data={"latitude": "0.3533", "longitude": "32.7553"},
        )
        times.append((time.perf_counter() - t0) * 1000.0)
        statuses.append(r.status_code)

    ok = [t for t, s in zip(times, statuses) if s == 200]
    print(f"HTTP POST /diagnose  n={len(times)}  successes={len(ok)}  "
          f"(payload ~{len(payload)//1024} KB, 1280x960 source)")
    if not ok:
        print("all failed", statuses)
        return 1
    ok_sorted = sorted(ok)
    print(f"  min    = {min(ok):7.1f} ms")
    print(f"  median = {statistics.median(ok):7.1f} ms")
    print(f"  mean   = {statistics.fmean(ok):7.1f} ms")
    print(f"  p95    = {ok_sorted[int(0.95 * (len(ok_sorted) - 1))]:7.1f} ms")
    print(f"  max    = {max(ok):7.1f} ms")
    print(f"  statuses: {sorted(set(statuses))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
