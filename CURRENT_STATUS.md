# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R11-S0 冻结协议见 `docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`；正式结果见 `docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`。

**当前科学状态：R11-S0 已正式 COMPLETE，冻结结论为 `STOP_DEEP_CORE_ROUTE`；68/68 fits 完成，`selected_backbone=null`，final holdout 2019-03/06/09/12 未访问。原计划 R11-M1 不再授权启动，因为其前提是 S0 选出稳定 deep backbone。**

## 1. Accepted R11-S0 run

```text
launcher schema      evcf-r11-s0-launcher/v1.4.1
launcher SHA256      c6caaaf1a00aa41f8778aeb24ab0c55f1fee02a847e93c205439735aac987f42
reviewed executable  a7dceaabab7a27cf6a6323a4630ea38494ffed71
implementation merge bebe0ebcb94f1ce8a9bafd35156be0a94dcfbd87
formal fits          68 / 68
status               COMPLETE
decision             STOP_DEEP_CORE_ROUTE
holdout accessed     false
session predictors   false
```

Formal environment:

```text
NVIDIA GeForce RTX 5080 / cuda:0
PyTorch 2.14.0+cu132
CUDA 13.2
four-model deterministic CUDA forward/backward smoke PASS
```

## 2. Station-HGB anchor

Frozen pooled test identity: 5,075 origins × 5 horizons = 25,375 origin-horizon records.

```text
Station-HGB pooled MAE   25.8731522189 A
Station-HGB pooled RMSE  53.1466051439 A
Station-HGB pooled WAPE  0.1737126243
```

Horizon MAE:

```text
15 min   11.2074011740 A
30 min   17.4805070019 A
60 min   25.2404332683 A
120 min  33.2954316198 A
240 min  42.1419880303 A
```

## 3. Deep-screen result

```text
GRU      pooled MAE 27.2072425618 A   +5.16% vs HGB   spread 5.03%   ineligible
TCN      pooled MAE 26.9086600381 A   +4.00% vs HGB   spread 3.03%   ineligible
N-HiTS   pooled MAE 34.8304657865 A  +34.62% vs HGB   spread 5.31%   ineligible
PatchTST pooled MAE 32.3044344149 A  +24.86% vs HGB   spread 8.20%   ineligible
```

TCN is closest, but fails frozen eligibility on pooled MAE, worst-horizon degradation, worst-month degradation and seed spread. No threshold is relaxed after seeing results.

A useful diagnostic remains: TCN is substantially worse at 15–30 min, but slightly better than Station-HGB at 60/120/240 min. This is **development evidence only**, not a selected backbone and not permission to construct an ex-post ensemble inside S0.

## 4. Scientific consequence

The original R11 carrier assumption is rejected:

> one compact deep station-level backbone is not sufficiently credible, under the frozen S0 data/training budget, to carry the planned privileged-supervision experiment across all five horizons.

The privileged-information hypothesis itself has **not** been tested. What failed is the planned single-deep-backbone carrier.

Therefore:

```text
R11-S0     CLOSED / STOP_DEEP_CORE_ROUTE
R11-M1     DO NOT RUN AS ORIGINALLY DEFINED
fifth model / extra seed / tuning rescue  NOT ALLOWED
final holdout                           SEALED
```

## 5. Prior mechanism evidence still retained

Earlier development evidence remains valid:

- R6 oracle: already-connected-session error dominates at 15–30 min; future-arrival error dominates at 60–240 min.
- R7 requested-departure timing carries small incremental predictive information for future-arrival component.
- R10 robustness is `MIXED_DEVELOPMENT_ROBUSTNESS`; old method line remains frozen.

The S0 horizon pattern is directionally consistent with a regime boundary near 60 min, but horizon dependence itself is not a novelty claim.

## 6. Next action

Do **not** run more R11-S0 or access final holdout.

The next scientific task is to define a new, separately frozen post-S0 hypothesis that preserves aggregate-only deployment. The preferred design question is whether session-resolved component labels can be used as training-only supervision in a **mechanism-aligned residual/component formulation**, rather than forcing one deep model to replace Station-HGB at every horizon.

Any such route must be predeclared before new real-data fits.