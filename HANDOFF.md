# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、`docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md` 与 `docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`。

## 1. Frozen scientific state

```text
R10-R0 = MIXED_DEVELOPMENT_ROBUSTNESS, COMPLETE
R11-S0 protocol = FROZEN
R11-S0 formal run = COMPLETE
R11-S0 fits = 68 / 68
R11-S0 decision = STOP_DEEP_CORE_ROUTE
selected_backbone = null
R11-M1 as originally defined = NOT AUTHORIZED
final holdout = SEALED
```

Final JPL holdout remains `2019-03/06/09/12` and has not been accessed.

## 2. Accepted execution identity

```text
launcher schema      evcf-r11-s0-launcher/v1.4.1
launcher SHA256      c6caaaf1a00aa41f8778aeb24ab0c55f1fee02a847e93c205439735aac987f42
reviewed executable  a7dceaabab7a27cf6a6323a4630ea38494ffed71
implementation merge bebe0ebcb94f1ce8a9bafd35156be0a94dcfbd87
status SHA256        2706d5ed65e2d2c0e6ed5d2aace4fd9f95ccc23f61833a9d41f5184361e77f70
```

Formal environment:

```text
RTX 5080
PyTorch 2.14.0+cu132
CUDA 13.2
deterministic forward/backward smoke PASS for GRU/TCN/N-HiTS/PatchTST
```

## 3. Core result

Station-HGB pooled anchor:

```text
MAE   25.8731522189 A
RMSE  53.1466051439 A
WAPE  0.1737126243
```

Deep candidates:

```text
GRU      27.2072425618 A  (+5.16%)  ineligible
TCN      26.9086600381 A  (+4.00%)  ineligible
N-HiTS   34.8304657865 A (+34.62%)  ineligible
PatchTST 32.3044344149 A (+24.86%)  ineligible
```

TCN is closest but still fails the frozen pooled, worst-horizon, worst-month and seed-spread gates. No rescue, fifth architecture, extra seed, clipping, calibration or threshold relaxation is allowed inside R11-S0.

## 4. Diagnostic signal

TCN horizon MAE relative to Station-HGB:

```text
15 min   +49.36%
30 min   +11.87%
60 min    -2.22%
120 min   -1.01%
240 min   -3.35%
```

This does not overturn STOP. It is only motivation for a future separately frozen hypothesis.

Earlier mechanism evidence should be read together with this result:

```text
R6: existing-session error dominates 15–30 min; arrival error dominates 60–240 min
R7: requested-departure timing gives small incremental arrival-component information
R10: MIXED_DEVELOPMENT_ROBUSTNESS; old method line frozen
```

The convergence around a ~60 min regime boundary is scientifically interesting, but generic horizon dependence is already known and must not be sold as novelty by itself.

## 5. Current research boundary

The failed object is the **single deep station-level carrier**, not the broader idea of using session-resolved information only during training.

Do not run the originally planned R11-M1. A new route, if pursued, must be independently specified and frozen before fitting.

Preferred next design question:

> Can session-resolved existing/arrival labels be used as training-only supervision for a station-only residual/component forecaster that keeps the strong Station-HGB anchor, especially at arrival-dominated 60–240 min horizons, without requiring session information at inference?

This is a design question only; no new real-data fit has been authorized after S0.

## 6. Hygiene

Preserve all worktrees, status files and caches. No reset/clean/stash/force-push/automatic deletion. Do not access final holdout. Avoid unnecessary GitHub Actions while the next protocol is being designed.