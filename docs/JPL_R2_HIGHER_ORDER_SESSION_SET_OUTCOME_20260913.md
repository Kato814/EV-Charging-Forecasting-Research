# JPL/ACN R2 higher-order origin-active session-set outcome

Date: 2026-09-13

Status: **COMPLETE — STOP_HIGHER_ORDER_SET_ROUTE**

This document records the single authorized development-only R2 run under `docs/JPL_R2_HIGHER_ORDER_SESSION_SET_PROTOCOL_20260912.md`. It does not reopen tuning and does not authorize final-holdout access.

## 1. Run identity and integrity

- reviewed implementation head: `1ec7b02bb0e44353034aa86678ce039e747a589f`
- protocol merge: `ab0b8f6b7521f9e55d65a82fe7d44140a0973fef`
- implementation merge: `b1093ab6580a5153346f6b8c4981b2d2ba20b51e`
- formal fit count: **550**
- runtime: **448.055812 s** (~7.47 min)
- device: `cuda:0`, NVIDIA GeForce RTX 5080
- PyTorch: `2.14.0+cu132`; CUDA runtime: `13.2`
- development months: `2019-01`, `2019-04`, `2019-07`, `2019-10`
- final holdout `2019-03/06/09/12`: **not accessed**
- development data unchanged after run: **true**
- accepted R1 private cache unchanged after run: **true**
- existing worktrees preserved: **true**
- no hyperparameter search, clipping, calibration, future-session generation, MoE, Set Transformer or reference-model retraining.

Formal R2 private manifest SHA256:

`9f35cffc192ebcebe30204fa1d23137ffc41e8ba858d9c55acfa85952d09bdd6`

## 2. Frozen primary result

Pooled MAE (A):

| Model | MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Joint | 29.039978 |
| **R2-Permuted** | **33.329417** |
| **R2-Joint** | **33.566025** |

Relative to the matched R2-Permuted control, R2-Joint is **0.7099% worse** in pooled MAE. Relative to Equal, S1 and R1-Joint, R2-Joint is respectively about **16.08%**, **17.38%** and **15.59%** worse.

The primary counterfactual therefore fails: preserving the true same-session cross-field alignment did not improve pooled development performance over the marginal-preserving permuted control.

## 3. Horizon and month support

Joint beats Permuted on only **2/5 horizons**:

- 15 min: Joint 10.053948 < Permuted 10.328399 A
- 30 min: Joint 17.643489 < Permuted 17.706466 A
- 60 min: Joint 30.013413 > Permuted 29.654114 A
- 120 min: Joint 47.334076 > Permuted 46.781030 A
- 240 min: Joint 62.785200 > Permuted 62.177076 A

Joint beats Permuted on only **1/4 development months**:

- Jan: Joint 28.829052 > Permuted 28.659078 A
- Apr: Joint 35.842927 > Permuted 35.251325 A
- Jul: Joint 33.532278 > Permuted 33.186842 A
- Oct: Joint 36.296484 < Permuted 36.424659 A

R2-Joint beats Equal on **0/5 horizons and 0/4 months**, and beats S1 on **0/5 horizons and 0/4 months**. At 60 min, Joint = 30.013413 A versus Equal = 26.141292 A. The maximum horizon degradation relative to the better of Equal/S1 is 21.7006%.

## 4. Frozen decision

The preregistered STOP rule is triggered independently by two conditions:

1. pooled R2-Joint MAE >= pooled R2-Permuted MAE; and
2. R2-Joint beats R2-Permuted on only 1/4 development months.

Formal decision:

`STOP_HIGHER_ORDER_SET_ROUTE`

This closes the current higher-order set route as the core method. Per protocol, do **not** rescue it after seeing the result with Set Transformer, attention pooling, larger Deep Sets, MoE/horizon routing, permutation search, clipping/calibration, row/date deletion, or final-holdout access.

## 5. Interpretation boundary

The result does **not** prove that all session-level or set representations are useless. It shows that, under the frozen R2 matched experiment, the true higher-order same-session alignment did not provide sufficient stable predictive value beyond exactly preserved per-field marginals, and the fixed low-capacity set model was materially less competitive than the accepted practical baselines.

The 15/30-min Joint-vs-Permuted gains are local descriptive observations only. They do not override the pooled/month STOP conditions and cannot be used to create a post-hoc horizon gate.

No additional R2 training is authorized from this outcome. Any subsequent research direction must be a new question with a new preregistered protocol and must keep the final holdout sealed.

## 6. Console-output usability note

The formal run produced substantially more progress output than needed because it reported coarse epoch progress for each individual fit. Future long-running launchers should use stage-level progress only: device/environment, current month, current horizon, completed fits/total fits, and elapsed time. Epoch-level logs should be suppressed unless needed for debugging a failure.
