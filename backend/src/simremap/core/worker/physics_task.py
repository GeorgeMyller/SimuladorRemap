"""``PhysicsOnlyTask``: ``SimTask`` headless com a física real (T408; D-04; platform OQ-01).

Corre o ``PhysicsEngine`` a ``sim_hz`` com o piloto de referência (``ReferenceDriver``, sem
ECU) e o banco de rotação constante (``RpmHoldRig``) e emite ``telemetry.frame`` a ``fps``
(fronteira ``floor(k · fps / sim_hz)``, como o ``TelemetrySampler``). Serve de carga real
para o benchmark ``process`` × ``thread`` do worker (``tests/core/bench``) e não depende
da ECU, do dinamómetro completo nem do banco de dados (nunca importa ``fastapi``).

``init_payload`` (JSON, todos opcionais)::

    {"vehicle_id": "hatch-20t-gdi", "fuel_id": null, "vehicle": null, "fuel": null,
     "catalog_dir": null, "sim_hz": 1000, "fps": 50, "seed": 0, "noise": true,
     "rpm": 4000.0, "throttle_pct": null, "ect_c": 90.0}

- ``vehicle``/``fuel``: ``VehicleSpec``/``FuelSpec`` serializados (o host já validou o
  catálogo); sem eles, o veículo e o combustível vêm do catálogo empacotado
  (``catalog_dir`` opcional) por ``vehicle_id``/``fuel_id`` (padrão: combustível de série).
- ``rpm``: rotação segurada pelo banco; ``throttle_pct``: ``null`` = plena carga do
  ``reference_command_schedule``.

Comandos (``type``): ``set_rpm`` (``rpm``), ``set_throttle`` (``throttle_pct`` ou
``null``), ``run.state`` (→ ``run.state``), ``echo`` (→ ``ack``); outros → ``ack`` com
``ignored``. O ``teardown`` emite ``run.state`` ``closed`` com ``ticks`` e o
``state_digest`` final (determinismo: mesma entrada e ``seed`` → mesmo digest).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import orjson

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.physics.contracts import EngineState, PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig

__all__ = ["DEFAULT_VEHICLE_ID", "PhysicsOnlyTask"]

DEFAULT_VEHICLE_ID: Final = "hatch-20t-gdi"
RPM_MIN, RPM_MAX = 500.0, 9000.0  # rev/min, faixa aceite para o banco


def _num(value: object, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} deve ser numérico")
    number = float(value)
    if not low <= number <= high:
        raise ValueError(f"{name} fora de [{low}, {high}]: {number}")
    return number


def _round(value: float | None, nd: int = 4) -> float | None:
    return None if value is None else round(value, nd)


class PhysicsOnlyTask:
    """Física real em regime de banco: um ``step`` por ``tick``, frames a ``fps``."""

    def __init__(self) -> None:
        self.sim_hz = 1000
        self.fps = 50
        self.tick_index = 0
        self.frame_index = -1
        self.engine: PhysicsEngine | None = None
        self.driver: ReferenceDriver | None = None
        self.rig: RpmHoldRig | None = None
        self.state: EngineState | None = None
        self.vehicle_id = DEFAULT_VEHICLE_ID
        self._outputs: list[bytes] = []

    # ------------------------------------------------------------------ helpers
    @property
    def t_sim_s(self) -> float:
        return self.tick_index / self.sim_hz

    def _emit(self, kind: str, **payload: Any) -> None:
        self._outputs.append(
            orjson.dumps({"v": 1, "type": kind, "t_sim_s": self.t_sim_s, "payload": payload})
        )

    @staticmethod
    def _load_specs(options: dict[str, Any]) -> tuple[VehicleSpec, FuelSpec]:
        if options.get("vehicle") is not None:
            if options.get("fuel") is None:
                raise ValueError("'fuel' é obrigatório quando 'vehicle' é enviado")
            vehicle = VehicleSpec.model_validate(options["vehicle"])
            return vehicle, FuelSpec.model_validate(options["fuel"])
        from simremap.catalog.loader import load_catalog_data  # noqa: PLC0415 - só sem specs

        catalog_dir = options.get("catalog_dir")
        catalog = load_catalog_data(Path(catalog_dir) if catalog_dir else None)
        vehicle_id = str(options.get("vehicle_id") or DEFAULT_VEHICLE_ID)
        entry = catalog.vehicles.get(vehicle_id)
        if entry is None:
            raise ValueError(f"veículo desconhecido: {vehicle_id}")
        fuel_id = str(options.get("fuel_id") or entry.spec.stock_fuel_id)
        if fuel_id not in entry.spec.allowed_fuel_ids or fuel_id not in catalog.fuels:
            raise ValueError(f"combustível {fuel_id} não permitido em {vehicle_id}")
        return entry.spec, catalog.fuels[fuel_id]

    # ------------------------------------------------------------------ SimTask
    def setup(self, init_payload: bytes) -> None:
        options = orjson.loads(init_payload) if init_payload else {}
        if not isinstance(options, dict):
            raise ValueError("init_payload deve ser um objeto JSON")
        vehicle, fuel = self._load_specs(options)
        self.vehicle_id = vehicle.vehicle_id
        self.sim_hz = int(_num(options.get("sim_hz", 1000), 100, 1000, "sim_hz"))
        self.fps = int(_num(options.get("fps", 50), 1, 60, "fps"))
        config = PhysicsConfig(
            sim_hz=self.sim_hz,
            seed=int(_num(options.get("seed", 0), 0, 2**63 - 1, "seed")),
            noise_enabled=bool(options.get("noise", True)),
        )
        ect = _num(options.get("ect_c", 90.0), -20.0, 120.0, "ect_c")
        self.engine = PhysicsEngine(config, vehicle, fuel, initial_ect_c=ect)
        throttle = options.get("throttle_pct")
        self.driver = ReferenceDriver(
            self.engine,
            vehicle.reference_command_schedule,
            throttle_pct=None if throttle is None else _num(throttle, 0.0, 100.0, "throttle_pct"),
        )
        rpm = _num(options.get("rpm", 4000.0), RPM_MIN, RPM_MAX, "rpm")
        self.rig = RpmHoldRig(target_rpm=rpm)
        self.engine.crank(rpm)
        self._emit("run.state", state="idle", vehicle_id=vehicle.vehicle_id, fuel_id=fuel.fuel_id)

    def handle_command(self, command: dict[str, object]) -> None:
        kind = command.get("type")
        if kind == "set_rpm" and self.rig is not None:
            self.rig.target_rpm = _num(command.get("rpm"), RPM_MIN, RPM_MAX, "rpm")
            self._emit("ack", command="set_rpm", rpm=self.rig.target_rpm)
        elif kind == "set_throttle" and self.driver is not None:
            value = command.get("throttle_pct")
            self.driver.throttle_override = (
                None if value is None else _num(value, 0.0, 100.0, "throttle_pct")
            )
            self._emit("ack", command="set_throttle", throttle_pct=self.driver.throttle_override)
        elif kind == "run.state":
            self._emit("run.state", state=command.get("state", "idle"))
        elif kind == "echo":
            self._emit("ack", command="echo", value=command.get("value"))
        else:
            self._emit("ack", command=str(kind), ignored=True)

    def tick(self) -> None:
        engine, driver, rig = self.engine, self.driver, self.rig
        if engine is None or driver is None or rig is None:
            raise RuntimeError("PhysicsOnlyTask sem setup")
        dt = 1.0 / self.sim_hz
        sensors = engine.read_sensors()
        commands = driver.commands(sensors, dt)
        self.state = engine.step(commands, rig.load(self.state, engine.rpm, dt), dt)
        self.tick_index += 1
        frame = (self.tick_index * self.fps) // self.sim_hz
        if frame != self.frame_index:
            self.frame_index = frame
            self._emit_frame(frame)

    def _emit_frame(self, frame: int) -> None:
        st = self.state
        if st is None:  # pragma: no cover - tick grava o estado antes do frame
            return
        self._emit(
            "telemetry.frame",
            frame_index=frame,
            rpm=_round(st.rpm, 2),
            map_kpa=_round(st.map_kpa, 3),
            boost_kpa=_round(st.boost_pre_throttle_kpa, 3),
            torque_nm=_round(st.torque_nm, 3),
            power_kw=_round(st.power_kw, 3),
            whp=_round(st.whp, 3),
            lambda_collector=_round(st.lambda_collector),
            egt_c=_round(st.egt_collector_c, 2),
            iat_c=_round(st.iat_c, 2),
            ect_c=_round(st.ect_c, 2),
            turbo_rpm=_round(st.turbo_rpm, 1),
            knock_events=sum(1 for _ in st.events),
        )

    def drain_outputs(self) -> list[bytes]:
        outputs, self._outputs = self._outputs, []
        return outputs

    def teardown(self) -> None:
        digest = self.engine.state_digest() if self.engine is not None else None
        self._emit("run.state", state="closed", ticks=self.tick_index, state_digest=digest)
