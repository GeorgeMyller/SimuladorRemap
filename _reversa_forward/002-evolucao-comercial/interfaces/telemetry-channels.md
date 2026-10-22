# Interface: canais novos de telemetria (WS `telemetry.frame`)

| Canal | Unidade | Fonte |
|---|---|---|
| `cam_intake_deg` | ° | posição real do came de admissão (`SensorReadings.cam_intake_deg`) |
| `cam_exhaust_deg` | ° | posição real do came de escape |
| `cam_intake_target_deg` | ° | alvo da ECU (`ActuatorCommands.vvt_intake_target_deg`) |
| `cam_exhaust_target_deg` | ° | alvo da ECU |
| `ethanol_pct` | % | sensor flex (null sem flex) |

Canais só são enviados quando subscritos (`control.subscribe`), como os demais.
