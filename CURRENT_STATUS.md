# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，论文可行性判断见 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)，R11 算法方向筛选见 [R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)，最新冻结协议见 [R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE；Post-R10 paper viability=`CONDITIONAL_MECHANISM_PAPER_VIABILITY`。用户已明确要求继续算法探索且核心方法应适用于站点级数据。`R11-S0` 站点级深度 backbone 筛选协议已冻结；当前下一步为实现、测试、参数量/CUDA preflight、代码审查与 pinned launcher，尚未授权真实模型拟合。final holdout 2019-03/06/09/12 继续封存。**

## 1. Accepted development candidate

Departure-representation refinement remains closed. Retain R7 `Departure-Aug / TotalDeparture` as the accepted development-stage candidate of the old structured line:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R10 does not revoke the R7 development signal, but it does not qualify the candidate for final holdout.

## 2. R10-R0 formal result

```text
status                         COMPLETE
decision                       MIXED_DEVELOPMENT_ROBUSTNESS
status SHA256                  058ec6b1196c76e884973e36f851e5c05831bb16fc6533b240d445c4dd82dda8
protocol commit                05dc342d376425c13f09ee68356583223203aae3
reviewed executable            753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge           062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
launcher SHA256                e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                      0
holdout accessed               false
R7 private cache unchanged     true
```

Exact pooled replay passed.

## 3. Frozen R10 decision support

```text
                                        vs S1          vs Equal
pooled improvement                      +0.5575%       +1.6662%
original month wins                     3/4            3/4
original horizon wins                   4/5            4/5
local-day wins                          26/55          31/55
local-day win rate                      47.27%         56.36%
leave-one-month-out wins                4/4            4/4
leave-one-horizon-out wins              5/5            5/5
worst original-month degradation        1.004%         1.675%
```

FRAGILE does not apply. READY fails only the frozen `>=50%` local-day win-rate requirement versus S1: observed `26/55 = 47.27%`. Therefore the exhaustive preregistered decision is `MIXED_DEVELOPMENT_ROBUSTNESS`.

## 4. Scientific result retained after R10

The accepted evidence chain is:

1. future load composition shifts from issue-time connected sessions toward future arrivals as horizon increases;
2. R4 shows richer legal issue-time state is informative but does not remove substantial future-state ambiguity;
3. R6 shows the larger removable error source changes from existing-session evolution at 15–30 min to future-arrival error at 60–240 min;
4. R7/R7-D1 show requested-departure timing of current sessions provides incremental predictive information for the future-arrival component beyond declaration availability;
5. R8/R9 close further departure representation engineering;
6. R10 shows the small total-load gain survives month/horizon deletion but is not broad enough across days for holdout readiness.

The pooled gain is not a single-month or single-horizon artifact, but the limiting evidence remains day-level breadth versus S1:

```text
mean daily delta vs S1       -0.16134 A
median daily delta vs S1     +0.05723 A
top-5 gain share vs S1        60.66%
```

## 5. Revised algorithm objective

Post-R10 synthesis remains:

```text
CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

R7 is not strong enough to be positioned as a major new forecasting algorithm. The mechanism evidence remains useful, but the project now continues toward a **portable station-level deep forecasting method**.

The minimum deployment contract is:

> the deployed model must operate from ordinary station-level load/history and timestamp context; session-resolved information may support source-side training or mechanism analysis but must not be required at inference.

Generic `multi-scale + multi-horizon`, Transformer/PatchTST/TCN choice, horizon conditioning and generic knowledge distillation are treated as prior-art/backbone tools rather than novelty claims.

The selected research direction remains:

> **station-level multi-horizon core + session-resolved training-only auxiliary supervision**.

The later scientific test is whether fine-grained ACN component labels can improve an aggregate-only forecaster while the inference feature contract stays station-level.

## 6. R11-S0 protocol now frozen

`R11-S0` = station-level deep-backbone screening.

Frozen station-only input contract:

```text
24 h history = 96 x 15-min bins
history channels = standardized aggregate station current + validity mask
issue/target timestamp calendar context only
no session-derived predictor
```

Frozen horizons:

```text
15 / 30 / 60 / 120 / 240 min
```

Frozen candidate families:

```text
GRU      2 layers, hidden 96
TCN      5 causal residual blocks, dilations 1/2/4/8/16
N-HiTS   3 hierarchical stacks, pooling 1/4/16
PatchTST compact control, patch 16 / stride 8 / d_model 64 / 2 layers
```

Common deep training policy:

```text
AdamW, lr=1e-3, weight_decay=1e-4
batch=256
max_epochs=120
patience=12
SmoothL1 five-horizon loss
3 frozen seeds
float32 / RTX 5080 / no AMP
```

Chronology is month-wise expanding and causal: earlier development months plus current-month days 1–14 train; current days 15–17 validate; current day >=18 is the exact frozen formal test set.

Formal ceiling:

```text
48 deep fits + 20 Station-HGB fits = 68 fits
```

No formal fit is authorized until implementation/code review/CI/pinned-launcher freeze is complete.

## 7. R11-S0 selection rule

`Station-HGB` uses the same station-only information as a non-deep anchor with frozen per-horizon HGB parameters.

A deep candidate is eligible to carry R11-M1 only if, on median-of-three-seed metrics:

```text
pooled MAE <= 1.02 * Station-HGB pooled MAE
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four chronological folds complete
```

Decisions:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

If multiple candidates are eligible, choose the lowest pooled median MAE; if top two differ by <0.25%, choose the smaller trainable-parameter count. No fifth architecture may be added after seeing R11-S0 results.

Frozen S1/Equal/R7 may be reported only as richer-information context, not as the station-only S0 selection threshold.

## 8. Planned R11-M1

Only after `SELECT_STATION_BACKBONE` may a separate protocol compare:

```text
Arm 1: selected station-level backbone + total-load supervision
Arm 2: identical station-level inputs/backbone + training-only E/A auxiliary supervision
```

Session-resolved component truths are labels only. They never become deployment inputs.

If the auxiliary-supervision effect is absent or unstable, the route closes; do not respond by adding session predictors or changing the backbone after seeing the result.

## 9. Current prohibitions

Do not:

- open or prepare the JPL final holdout;
- run R11-S0 before executable/launcher freeze;
- rerun/tune R7 to repair R10;
- return to requested-departure feature/bin engineering as the prediction method;
- use session/future information as inference input;
- tune R11 depth, patch length, dilation pattern, learning rate or dropout after observing results;
- add Mamba/SSM/a fifth backbone after R11-S0;
- ensemble/select seeds;
- select favorable months/horizons/datasets after observing results;
- claim generic backbone/multi-scale/multi-horizon/KD concepts as new.

R9 and R10 outcomes remain unchanged.

## 10. Immediate next action

The R11-S0 scientific protocol is frozen. The next authorized work is **implementation only, without real-data fitting**:

1. create an isolated R11 code branch;
2. implement station-only dataset construction, Station-HGB and four deep candidates;
3. add chronology/no-session/row-identity/output-shape unit tests;
4. run shape-only parameter-count preflight and freeze any width-only correction needed to stay within 50k–250k parameters;
5. add CUDA/RTX 5080 preflight with no CPU fallback for the formal run;
6. review the code and freeze the reviewed executable;
7. conserve GitHub Actions and run full CI once on the final candidate;
8. create one pinned launcher;
9. only after those steps may the user run the one formal 68-fit R11-S0 screen.
