"""End-to-end test for country module v1.

Usage: python -m scripts.e2e_country

Requires:
  - Postgres running (docker-compose up db)
  - Migrations applied (alembic upgrade head)
  - Backend running (uvicorn app.main:app)
  - A valid JWT token (set E2E_TOKEN env var, or cookie from browser)

Steps:
  1. POST /api/jobs {command: "country_refresh", params: {}}
  2. Poll GET /api/jobs/{id} until done or failed (timeout 300s)
  3. GET /v1/countries — verify 10 countries returned, all scored
  4. GET /v1/country/US/summary?include_evidence=true — verify packet structure
  5. Print summary table
"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
TOKEN = os.environ.get("E2E_TOKEN", "")

if not TOKEN:
    print("ERROR: Set E2E_TOKEN env var to a valid JWT token")
    print("  You can copy it from the access_token cookie in your browser.")
    sys.exit(1)


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def main():
    client = httpx.Client(base_url=BASE, timeout=30)

    # 1. Submit country_refresh job
    print("=== Step 1: Submit country_refresh job ===")
    r = client.post(
        "/api/jobs",
        json={"command": "country_refresh", "params": {}},
        headers=headers(),
    )
    assert r.status_code == 200, f"Failed to submit job: {r.status_code} {r.text}"
    job = r.json()
    job_id = job["id"]
    print(f"  Job submitted: {job_id}")

    # 2. Poll until done or failed
    print("\n=== Step 2: Poll job status ===")
    timeout = 300
    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"/api/jobs/{job_id}", headers=headers())
        assert r.status_code == 200
        status = r.json()["status"]
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] Status: {status}")
        if status in ("done", "failed", "cancelled"):
            break
        time.sleep(5)
    else:
        print(f"  TIMEOUT after {timeout}s")
        sys.exit(1)

    if status != "done":
        print(f"  Job {status}. Check logs at /api/jobs/{job_id}/stream")
        sys.exit(1)

    print(f"  Job completed in {int(time.time() - start)}s")

    # 3. GET /v1/countries
    print("\n=== Step 3: Verify /v1/countries ===")
    r = client.get("/v1/countries", headers=headers())
    assert r.status_code == 200, f"Countries endpoint failed: {r.status_code}"
    countries = r.json()
    assert len(countries) == 10, f"Expected 10 countries, got {len(countries)}"

    print(f"  {'Rank':<5} {'Country':<20} {'Overall':>8} {'Macro':>8} {'Market':>8} {'Stability':>10}")
    print(f"  {'-'*5} {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for c in countries:
        print(
            f"  #{c['rank']:<4} {c['name']:<20} {c['overall_score']:>8.1f} "
            f"{c['macro_score']:>8.1f} {c['market_score']:>8.1f} {c['stability_score']:>10.1f}"
        )
        # Verify score ranges
        for key in ("overall_score", "macro_score", "market_score", "stability_score"):
            assert 0 <= c[key] <= 100, f"{c['iso2']} {key}={c[key]} out of range"
        assert c["calc_version"] == "country_v1"

    print(f"\n  All 10 countries scored. Scores in range [0, 100].")

    # 4. GET /v1/country/US/summary?include_evidence=true
    print("\n=== Step 4: Verify /v1/country/US/summary ===")
    r = client.get("/v1/country/US/summary?include_evidence=true", headers=headers())
    assert r.status_code == 200, f"Summary endpoint failed: {r.status_code}"
    packet = r.json()

    assert packet["iso2"] == "US"
    assert packet["calc_version"] == "country_v1"
    assert packet["summary_version"] == "country_summary_v1"
    assert "scores" in packet
    assert "component_data" in packet
    assert "evidence" in packet
    assert packet["evidence"] is not None
    assert len(packet["evidence"]) > 0, "Evidence array should not be empty"

    print(f"  Country: {packet['country_name']}")
    print(f"  Overall: {packet['scores']['overall']:.1f}")
    print(f"  Rank: #{packet['rank']} / {packet['rank_total']}")
    print(f"  Evidence items: {len(packet['evidence'])}")
    print(f"  Risks: {len(packet['risks'])}")

    # Verify evidence chain
    for ev in packet["evidence"]:
        assert "artefact_id" in ev, f"Evidence missing artefact_id: {ev}"
        assert "source" in ev, f"Evidence missing source: {ev}"

    print("\n=== E2E PASSED ===")


if __name__ == "__main__":
    main()
