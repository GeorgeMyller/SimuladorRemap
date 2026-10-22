"""Benchmark antes/depois dos kernels nativos e ausência de ``worker.overrun`` (003 T025).

1. ``test_bench_tick_native_vs_python``: tick completo do dinamômetro (física + ECU + dano +
   telemetria) numa ``sweep_pull`` 2000 → 6000 rpm a 1000 Hz, nos 4 veículos, com
   ``SIMREMAP_NATIVE=off`` (antes) e ``auto`` (depois). Cada modo corre num subprocesso
   (o seletor é lido uma vez por processo). Regista média/P95/P99 por estágio e ticks
   acima de 1 ms; exige física nativa ≥ 2× mais rápida e o tick completo P99 < 1 ms.
2. ``test_bench_pull_1000hz_without_overrun``: a mesma puxada no worker real (modo
   ``process``, ``spawn``) a 1000 Hz; amostra as estatísticas a cada 1 s como o
   ``SimWorkerHost`` e conta as janelas com ≥ 5 % de ticks acima de ``dt`` (cada uma seria
   um ``worker.overrun``). Inclui uma ``multi_pull`` do hatch (arrefecimento a 10 passos
   por tick, com orçamento de parede de 10 ``dt``: ``wall_budget_ticks``, T031). Exige 0
   janelas com os kernels nativos.

Relatório JSON em ``SIMREMAP_BENCH_REPORT`` (padrão ``.bench/native_tick.json``). Também
corre como script: ``python tests/bench/test_bench_native_tick.py measure`` (um modo,
JSON no stdout) e ``... pull`` (worker real).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.bench

HERE = Path(__file__).resolve()
TESTS = HERE.parents[1]
REPORT = Path(os.environ.get("SIMREMAP_BENCH_REPORT", ".bench/native_tick.json"))
VEHICLES = ("hatch", "coupe", "classic", "muscle")
SIM_HZ = 1000
SWEEP = {"run_type": "sweep_pull", "start_rpm": 2000, "end_rpm": 6000, "ramp_rate_rpm_s": 1000}
RUN_ID = "01JAB0000000000000000000NB"
TICKS = int(os.environ.get("SIMREMAP_BENCH_TICKS", "9000"))
OVERRUN_RATIO = 0.05
# multi_pull: o arrefecimento corre a COOLDOWN_SPEEDUP (10) passos por tick (~750 µs com o
# nativo); o laço só conta overrun acima de 10 ``dt`` nesses ticks (T031).
MULTI = {
    "run_type": "multi_pull",
    "pull_count": 2,
    "cooldown_s": 15,
    "start_rpm": 2000,
    "end_rpm": 5000,
    "ramp_rate_rpm_s": 1000,
}


def _dyno_helpers() -> Any:
    name = "native_bench_dyno_helpers"
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(TESTS / "dyno"))
    spec = importlib.util.spec_from_file_location(name, TESTS / "dyno" / "dyno_helpers.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _payload_kwargs(name: str) -> dict[str, Any]:
    helpers = _dyno_helpers()
    vehicle = getattr(helpers._physics_fixtures(), f"build_{name}")()
    fuel = helpers.catalog_fuels()[vehicle.stock_fuel_id]
    return {"vehicle": vehicle, "fuel": fuel, "sim_hz": SIM_HZ, "damage_config": None}


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class _Stage:
    """Proxy que soma o tempo de parede de ``step``/``on_tick``/``read_sensors``."""

    def __init__(self, real: Any, name: str, acc: dict[str, float]) -> None:
        self._real = real
        self._name = name
        self._acc = acc

    def __getattr__(self, attr: str) -> Any:
        value = getattr(self._real, attr)
        if attr not in ("step", "on_tick", "read_sensors"):
            return value
        key = f"{self._name}.{attr}"
        acc = self._acc

        def timed(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return value(*args, **kwargs)
            finally:
                acc[key] = acc.get(key, 0.0) + time.perf_counter() - t0

        return timed


def measure_vehicle(name: str, ticks: int = TICKS) -> dict[str, Any]:
    """Tick completo em processo, com o modo nativo deste processo."""
    from simremap.core.native import native_enabled

    helpers = _dyno_helpers()
    task = helpers.make_task(**_payload_kwargs(name))
    parts = task.session
    physics_real = parts.physics
    acc: dict[str, float] = {}
    parts.physics = _Stage(parts.physics, "physics", acc)
    parts.ecu = _Stage(parts.ecu, "ecu", acc)
    parts.damage = _Stage(parts.damage, "damage", acc)
    task._main_damage = parts.damage
    parts.sampler = _Stage(parts.sampler, "sampler", acc)
    task.handle_command({"type": "run.start", "run_id": RUN_ID, "request": dict(SWEEP)})
    samples: list[float] = []
    for _ in range(ticks):
        t0 = time.perf_counter()
        task.tick()
        task.drain_outputs()
        samples.append(time.perf_counter() - t0)
    stages = {k: round(v / ticks * 1e6, 2) for k, v in sorted(acc.items())}
    return {
        "vehicle": name,
        "native": native_enabled(),
        "physics_native": bool(getattr(physics_real, "native", False)),
        "ticks": ticks,
        "tick_mean_us": round(sum(samples) / ticks * 1e6, 2),
        "tick_p95_us": round(_pct(samples, 0.95) * 1e6, 2),
        "tick_p99_us": round(_pct(samples, 0.99) * 1e6, 2),
        "tick_max_us": round(max(samples) * 1e6, 2),
        "ticks_over_1ms": sum(1 for s in samples if s > 1.0 / SIM_HZ),
        "stages_mean_us": stages,
        "physics_us": round(
            stages.get("physics.step", 0.0) + stages.get("physics.read_sensors", 0.0), 2
        ),
    }


def _subprocess(mode: str, command: str, *args: str) -> Any:
    env = dict(os.environ, SIMREMAP_NATIVE=mode)
    out = subprocess.run(  # noqa: S603 - o próprio módulo com o mesmo interpretador
        [sys.executable, str(HERE), command, *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(TESTS.parent),
        timeout=1800,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def _write(section: str, data: Any) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = json.loads(REPORT.read_text("utf-8")) if REPORT.exists() else {}
    doc[section] = data
    REPORT.write_text(json.dumps(doc, indent=2, ensure_ascii=False), "utf-8")


# ------------------------------------------------------------------ worker real
def pull_in_worker(
    name: str, request: dict[str, Any] | None = None, seconds_cap: float = 60.0
) -> dict[str, Any]:
    """Puxada no ``ProcessBackend`` a 1000 Hz; janelas de 1 s como o ``SimWorkerHost``."""
    from simremap.core.native import native_enabled
    from simremap.core.worker.host import ProcessBackend
    from simremap.core.worker.protocol import COMMAND_STOP, StatsSlot, WorkerConfig

    helpers = _dyno_helpers()
    payload = helpers.make_payload(**_payload_kwargs(name)).model_dump_json().encode("utf-8")
    backend = ProcessBackend(
        "bench", "simremap.dyno.runner:DynoSimTask", payload, SIM_HZ, WorkerConfig()
    )
    backend.start()
    stats = backend.stats
    commands: Any = backend.channels.commands
    try:
        deadline = time.monotonic() + 30.0
        while stats[StatsSlot.TICKS] < 1 and time.monotonic() < deadline:
            _drain(backend)
            time.sleep(0.01)
        req = dict(request or SWEEP)
        start = {"type": "run.start", "run_id": RUN_ID, "request": req}
        commands.put(start)
        windows: list[dict[str, float]] = []
        result_seen = False
        t_prev = time.monotonic()
        ticks_prev = stats[StatsSlot.TICKS]
        over_prev = stats[StatsSlot.OVERRUN_TICKS]
        t_end = t_prev + seconds_cap
        while time.monotonic() < t_end and not result_seen:
            result_seen = _drain(backend)
            now = time.monotonic()
            if now - t_prev >= 1.0:
                ticks = stats[StatsSlot.TICKS]
                over = stats[StatsSlot.OVERRUN_TICKS]
                d_ticks = ticks - ticks_prev
                d_over = over - over_prev
                windows.append(
                    {
                        "ticks": d_ticks,
                        "overrun_ticks": d_over,
                        "ratio": (d_over / d_ticks) if d_ticks > 0 else 0.0,
                        "rtf": d_ticks / (now - t_prev) / SIM_HZ,
                    }
                )
                t_prev, ticks_prev, over_prev = now, ticks, over
            time.sleep(0.005)
    finally:
        commands.put({"type": COMMAND_STOP})
        if not backend.join(5.0):
            backend.terminate()
    flagged = [w for w in windows if w["ratio"] >= OVERRUN_RATIO]
    return {
        "vehicle": name,
        "run_type": str((request or SWEEP)["run_type"]),
        "native": native_enabled(),
        "result_seen": result_seen,
        "windows": len(windows),
        "overrun_windows": len(flagged),
        "overrun_ticks": int(sum(w["overrun_ticks"] for w in windows)),
        "ticks": int(sum(w["ticks"] for w in windows)),
        "max_ratio": round(max((w["ratio"] for w in windows), default=0.0), 4),
        "min_rtf": round(min((w["rtf"] for w in windows), default=0.0), 4),
        "window_overruns": [int(w["overrun_ticks"]) for w in windows],
    }


def _drain(backend: Any) -> bool:
    """Consome as faixas de saída; ``True`` quando o resultado da puxada chegou."""
    import queue

    seen = False
    for lane in (backend.channels.critical, backend.channels.data):
        while True:
            try:
                raw = lane.get_nowait()
            except queue.Empty:
                break
            if isinstance(raw, bytes) and b'"run.result"' in raw:
                seen = True
    return seen


# ------------------------------------------------------------------ testes
def test_bench_tick_native_vs_python() -> None:
    before = _subprocess("off", "measure")
    after = _subprocess("auto", "measure")
    if not any(r["physics_native"] for r in after):
        pytest.skip("extensão simremap_rs ausente: sem 'depois' para comparar")
    rows = []
    for b, a in zip(before, after, strict=True):
        rows.append(
            {
                "vehicle": b["vehicle"],
                "physics_us": [b["physics_us"], a["physics_us"]],
                "tick_mean_us": [b["tick_mean_us"], a["tick_mean_us"]],
                "tick_p99_us": [b["tick_p99_us"], a["tick_p99_us"]],
                "ticks_over_1ms": [b["ticks_over_1ms"], a["ticks_over_1ms"]],
            }
        )
    _write("tick", {"before": before, "after": after, "summary": rows})
    print(json.dumps(rows, ensure_ascii=False))
    for b, a in zip(before, after, strict=True):
        assert a["physics_us"] * 2.0 <= b["physics_us"], (b, a)
        assert a["tick_mean_us"] < b["tick_mean_us"], (b, a)
        assert a["tick_p99_us"] < 1e6 / SIM_HZ, a


def test_bench_pull_1000hz_without_overrun() -> None:
    after = _subprocess("auto", "pull")
    if not after[0]["native"]:
        pytest.skip("extensão simremap_rs ausente")
    before = _subprocess("off", "pull")
    # Uma nova tentativa por puxada sinalizada: absorve preempção do SO em máquina carregada.
    retried = []
    for i, r in enumerate(after):
        if r["overrun_windows"]:
            command = "pull1" if r["run_type"] == "sweep_pull" else "multi1"
            again = _subprocess("auto", command, r["vehicle"])[0]
            retried.append({"first": r, "retry": again})
            after[i] = again
    _write("pull_1000hz", {"before": before, "after": after, "retried": retried})
    print(json.dumps({"before": before, "after": after, "retried": retried}, ensure_ascii=False))
    for b, a in zip(before, after, strict=True):
        assert a["result_seen"], a
        assert a["overrun_windows"] == 0, a
        if a["run_type"] == "multi_pull":
            # Arrefecimento a 10 passos/tick: o nativo tem de manter o tempo real.
            assert a["min_rtf"] >= 0.97, a
            assert a["overrun_ticks"] <= b["overrun_ticks"], (b, a)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "measure"
    names = sys.argv[2:] or list(VEHICLES)
    if command == "measure":
        print(json.dumps([measure_vehicle(n) for n in names]))
    elif command == "pull":
        runs = [pull_in_worker(n) for n in names]
        runs.append(pull_in_worker("hatch", MULTI))
        print(json.dumps(runs))
    elif command == "pull1":
        print(json.dumps([pull_in_worker(n) for n in names]))
    elif command == "multi1":
        print(json.dumps([pull_in_worker(n, MULTI) for n in names]))
    else:
        raise SystemExit(f"comando desconhecido: {command}")
