# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、R4-I0/R4-D1/R4-D2 outcome、[R5 protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md)、[R5 geometry audit repair](docs/JPL_R5_GEOMETRY_AUDIT_SCALE_REPAIR_20260913.md) 和 [R5 outcome](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_OUTCOME_20260914.md)。

## 1. Frozen scientific state

```text
S1    = MIXED_STRUCTURED_SIGNAL, CLOSED
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1 = COMPLETE diagnostic
R4-D2 = COMPLETE diagnostic
R5    = STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE, CLOSED
```

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun S1/P1/R1/R2/R3/R4/R5 unless a separate frozen repair protocol explicitly requires replay.

## 2. Formal R5 identity and validity

Single authorized R5 development run:

```text
source status SHA256            d3c820d90cb4d54a56f50bd9d1293aa1a3e53da50d3418ddb34abc6fa6a8a196
launcher SHA256                 bde5df90397004304f3489afc633ed115492be8be3c9fb6a52f4bbe80dd2e975
protocol merge                  3f964696606f05bdc01b6f0b217e821d0f1933bf
geometry repair merge           431e1fe2fede50216d36ab89a5e61a835a29e737
reviewed executable             4f2925cba92d606b929a25dc84468fcc16f1afc4
implementation merge            efec1cce23daf64da20afd254d92d5eb79f9cf3e
fit_count                       110
holdout_accessed                false
development_data_unchanged      true
reference_models_retrained      false
```

Environment matched the frozen contract: Python 3.11.16 / PyTorch 2.14.0+cu132 / CUDA 13.2 / NVIDIA GeForce RTX 5080.

## 3. Formal R5 result

```text
decision                         STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE
Direct pooled MAE                35.013762 A
FTAR pooled MAE                  35.001553 A
M3 pooled MAE                    29.190188 A
Equal pooled MAE                 28.917286 A
S1 pooled MAE                    28.594882 A
FTAR vs Direct improvement       +0.0348677%
horizon wins                     3/5
month wins                       1/4
max horizon degradation          1.01985%
geometry Spearman Direct         0.378605
geometry Spearman FTAR           0.470014
```

STOP is triggered by the pre-registered month-stability rule (`1/4` month wins). FTAR remains about 21.0% worse than Equal and 22.4% worse than S1 in pooled MAE.

Horizon direction is small and mixed: FTAR improves Direct at 15/30/60 min, worsens 120/240 min. Month direction is unstable: January/April/July worsen; only October improves.

## 4. Scientific interpretation

R5 succeeds at the narrow representation objective but fails as a forecasting route:

- held-out same-refit latent/future-transition Spearman improves in all four development months;
- that improved latent geometry produces essentially no pooled MAE gain;
- strong frozen baselines remain substantially better.

Therefore the accepted conclusion is:

> Future-transition-aligned pairwise latent geometry can be learned, but geometry alignment alone is not sufficient to deliver stable or competitive station-load point forecasts under the frozen R5 contract.

Do not reinterpret this as evidence that all representation learning fails. It closes only the frozen FTAR mechanism.

## 5. No-rescue boundary

Do not revive or enlarge the following after R5:

- Level/M3 hard or neural gate, horizon/month router, MoE;
- P1 survival/TPP/count-mark escalation;
- R2 Deep Sets / Set Transformer / attention higher-order-set rescue;
- R3 control-endogeneity route;
- R5 larger MLP, Transformer/Mamba/Neural ODE, geometry-loss-weight tuning, clipping/calibration or post-hoc residual rescue.

The very large October Direct/FTAR RMSE relative to MAE may be investigated only as read-only failure analysis if needed; it must not be used to discard October or change the formal R5 decision.

## 6. Next research step

Return to candidate-direction selection using the complete S1–R5 evidence. The next mechanism must solve a remaining problem not already closed by prior experiments. Before any new model fit:

1. state one precise scientific question;
2. define a matched control that isolates the claimed mechanism;
3. freeze development-only causal/OOS evaluation and PASS/MIXED/STOP rules;
4. keep final holdout sealed;
5. only then implement and run.

No current user-side rerun is authorized.

## 7. Asset protection

Preserve all detached worktrees, status JSONs, R5 private cache (`private_manifest_sha256=45382977a3fceecec2c88dabffeaae8a9b24bddc6dc18669ddc94e2890006eb4`) and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees. Any future PowerShell instruction to the user must be one line.