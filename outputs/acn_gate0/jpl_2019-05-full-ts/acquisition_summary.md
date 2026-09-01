# JPL May 2019 full-month time-series QA

- QA gate: PASS
- Valid local daily chunks: 31/31
- Local-month rows: 1644
- Carry-in rows: 1
- Combined quality denominator: 1645
- Ready for cleaning: YES
- Ready for 15-minute use: YES_CURRENT_PROXY_ONLY
- Gate 1 readiness: NO

## Power semantics

chargingCurrent is measured current in amperes and is not direct kW.
pilotSignal is a control signal, not measured active power.
The only approved 15-minute representation is a current proxy.
Converting to kW requires voltage, phase, topology, power factor, and network context.
No fixed voltage assumption is made.

## Scope boundary

This artifact authorizes cleaning only when the QA gate passes. It creates no cleaned data, no 15-minute data, and no Gate 1 evidence.
