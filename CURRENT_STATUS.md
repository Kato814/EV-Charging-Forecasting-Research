# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R11-S0 冻结协议见 `docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`；正式结果见 `docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`；下一阶段协议见 `docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md`。

**当前科学状态：R11-S0 已正式 COMPLETE，冻结结论为 `STOP_DEEP_CORE_ROUTE`；68/68 fits 完成，`selected_backbone=null`，final holdout 2019-03/06/09/12 未访问。原计划 R11-M1 永久取消。新的 R11-P1 已完成方法论审查并冻结协议，但尚未实现、尚未运行。**

## 1. Accepted R11-S0 result

```text
formal fits          68 / 68
status               COMPLETE
decision             STOP_DEEP_CORE_ROUTE
selected_backbone    null
holdout accessed     false
session predictors   false
```

Station-HGB pooled anchor:

```text
MAE   25.8731522189 A
RMSE  53.1466051439 A
WAPE  0.1737126243
```

Deep candidates:

```text
GRU      27.2072425618 A   +5.16% vs HGB   ineligible
TCN      26.9086600381 A   +4.00% vs HGB   ineligible
N-HiTS   34.8304657865 A  +34.62% vs HGB   ineligible
PatchTST 32.3044344149 A  +24.86% vs HGB   ineligible
```

R11-S0 is closed. No fifth model, extra seed, threshold relaxation, clipping/calibration or rerun is allowed.

## 2. Mechanism evidence retained

Two already-observed development signals motivate the new protocol:

```text
R6 oracle:
15–30 min   existing-session evolution is the larger removable error source
60–240 min  future-arrival uncertainty is the larger removable error source

R11-S0 TCN vs Station-HGB:
15 min   +49.36%
30 min   +11.87%
60 min    -2.22%
120 min   -1.01%
240 min   -3.35%
```

The convergence around the 30–60 min boundary is development evidence only. Generic horizon dependence is not a novelty claim.

## 3. R11-P1 selected method question

R11-P1 asks:

> Can session-resolved **future-arrival contribution labels**, used only during training, improve a station-only 60–240 min forecaster when deployment still uses only aggregate station history/calendar and no session information?

The final five-horizon predictor is preregistered as a fixed horizon-gated hybrid:

```text
15 / 30 min      -> frozen same-information Station-HGB
60 / 120 / 240   -> station-only TCN branch
```

A direct `HGB + neural residual target` carrier was rejected during protocol design because leakage-free HGB residual targets would require nested chronological cross-fitting and would confound the privileged-supervision test.

## 4. R11-P1 arms

```text
Arm A  Station-HGB at all five horizons
Arm B  HGB 15/30 + TCN 60/120/240, total-load loss only
Arm C  HGB 15/30 + same TCN 60/120/240,
       total-load loss + 0.5 * future-arrival auxiliary loss
```

Arm B and C use identical station-only predictors, chronology, seeds and optimization. The arrival head exists only as a training-time auxiliary task and is discarded at deployment.

Inference still prohibits:

```text
session IDs
requested departure / requested energy
per-session pilot/current
existing/arrival truth
future sessions
```

## 5. Frozen R11-P1 decision

`PASS_PRIVILEGED_ARRIVAL_SUPERVISION` requires all of the following:

```text
C vs B pooled long-horizon MAE improvement >= 1.0%
C beats B in >= 2/3 long horizons
no long horizon degrades > 1.0% vs B
C beats B in >= 3/4 months
C beats B in >= 2/3 paired seeds
C pooled seed spread <= 3.0%
C long-horizon pooled MAE beats Station-HGB
complete five-horizon C hybrid beats Station-HGB pooled MAE
all folds complete; no frozen test rows removed
```

Other exhaustive outcomes:

```text
MIXED_PRIVILEGED_ARRIVAL_SIGNAL
STOP_PRIVILEGED_SUPERVISION_ROUTE
```

No lambda sweep, third neural arm, extra seed or horizon-boundary search is allowed.

## 6. Fit ceiling and next action

```text
Arm B  4 folds x 3 seeds = 12 deep fits
Arm C  4 folds x 3 seeds = 12 deep fits
R11-P1 deep fit ceiling  = 24
```

Station-HGB may be deterministically replayed only as the frozen anchor if row-level local predictions are required.

Current state:

```text
R11-P1 protocol        FROZEN
R11-P1 implementation  NOT YET DONE
R11-P1 formal run      NOT RUN
final holdout           SEALED
```

**下一步：实现 R11-P1，优先做针对性的本机 preflight/快速运行，不把全量 GitHub CI 作为每次小修的阻塞条件。**