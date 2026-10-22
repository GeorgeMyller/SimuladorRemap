"""Borboleta pelo WebSocket com a sessão real (003 T020, RF-13). Marcador ``e2e``:
``uv run --frozen pytest -m e2e tests/qa/test_throttle_ws.py``.

``control.throttle`` com o motor livre na bancada (sem puxada), app de produção em worker
``process`` e ``TestClient``:

- variação rápida 0 ↔ 100 % (blip de ~100 ms): o pedal da bancada sobe em rampa
  (≤ 100 %/s), sem erro no canal, e a rotação sobe e volta à lenta;
- pedal a fundo ~0,8 s: o motor sobe até o limitador e cai com corte de combustível;
- o motor continua íntegro e a sessão aceita uma puxada depois.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_support import API, Json, real_app

pytestmark = pytest.mark.e2e

CHANNELS: Final = ["rpm", "throttle_pct", "pedal_pct", "fuel_cut", "health_min_pct"]
BLIP_FRAMES: Final = 5  # ~100 ms a 50 quadros/s
HOLD_FRAMES: Final = 40  # ~0,8 s
SETTLE_FRAMES: Final = 150
IDLE_RPM_MAX: Final = 1200.0


@pytest.fixture
def client(settings_factory: Callable[..., Any]) -> Iterator[TestClient]:
    with TestClient(real_app(settings_factory(worker_mode="process"))) as c:
        yield c


class Bench:
    """Conexão do WebSocket que guarda os quadros e os erros recebidos."""

    def __init__(self, ws: WebSocketTestSession) -> None:
        self.ws = ws
        self.frames: list[dict[str, float]] = []
        self.errors: list[Json] = []

    def send(self, kind: str, **payload: Any) -> None:
        self.ws.send_json({"v": 1, "type": kind, "payload": payload})

    def pump(self, frames: int) -> list[dict[str, float]]:
        start = len(self.frames)
        while len(self.frames) - start < frames:
            message = self.ws.receive_json()
            if message["type"] == "telemetry.frame":
                self.frames.append(message["payload"]["channels"])
            elif message["type"] == "error":
                self.errors.append(message["payload"])
        return self.frames[start:]

    def throttle(self, pct: float, frames: int) -> list[dict[str, float]]:
        self.send("control.throttle", throttle_pct=pct)
        return self.pump(frames)


def _session(client: TestClient) -> str:
    resp = client.post(f"{API}/sessions", json={"vehicle_id": "hatch-20t-gdi", "seed": 3})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["session_id"])


def test_throttle_blips_and_full_pedal(client: TestClient) -> None:
    sid = _session(client)
    with client.websocket_connect(f"/ws/v1/sessions/{sid}/telemetry") as ws:
        assert ws.receive_json()["type"] == "run.state"
        bench = Bench(ws)
        bench.send("control.subscribe", channels=CHANNELS)
        idle = bench.throttle(0, 30)[-1]["rpm"]

        blips = []
        for _ in range(6):
            blips += bench.throttle(100, BLIP_FRAMES)
            blips += bench.throttle(0, BLIP_FRAMES)
        settled = bench.pump(SETTLE_FRAMES)
        full = bench.throttle(100, HOLD_FRAMES)
        released = bench.throttle(0, SETTLE_FRAMES)

    assert not bench.errors, bench.errors
    assert max(f["pedal_pct"] for f in blips) < 50.0  # rampa do pedal da bancada
    assert max(f["rpm"] for f in blips) > idle + 40.0
    assert settled[-1]["rpm"] < IDLE_RPM_MAX
    assert max(f["throttle_pct"] for f in full) == pytest.approx(100.0, abs=0.5)
    assert max(f["rpm"] for f in full) > 5000.0
    assert any(f["fuel_cut"] for f in released)
    assert released[-1]["pedal_pct"] == 0.0
    assert min(f["health_min_pct"] for f in bench.frames) == 100.0
    health = client.get(f"{API}/sessions/{sid}/engine/health").json()
    assert health["engine_locked"] is False
    run = client.post(f"{API}/sessions/{sid}/runs", json={"run_type": "baseline_pull"})
    assert run.status_code == 202, run.text
    assert client.delete(f"{API}/sessions/{sid}").status_code == 204
