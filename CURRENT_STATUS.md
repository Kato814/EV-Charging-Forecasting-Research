# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，论文可行性判断见 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)，最新算法方向筛选见 [R11 algorithm-direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE；Post-R10 paper viability=`CONDITIONAL_MECHANISM_PAPER_VIABILITY`。用户已明确要求继续算法探索且核心方法应适用于站点级数据。R11 方向筛选已完成，下一阶段为 `R11-S0` 站点级深度 backbone 筛选协议设计；当前尚未授权模型运行。final holdout 2019-03/06/09/12 继续封存。**

## 1. Accepted development candidate

Departure-representation refinement remains closed. Retain R7 `Departure-Aug / TotalDeparture` as the accepted development-stage candidate:

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

## 3. Frozen decision support

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

## 5. Paper viability and revised algorithm objective

Post-R10 synthesis remains:

```text
CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

R7 is not strong enough to be positioned as a major new forecasting algorithm. The mechanism evidence remains useful, but the user has clarified that the project should continue toward a **portable deep forecasting method**, not stop at mechanism replication.

The new minimum design contract is:

> the deployed model must operate from ordinary station-level load/history; session-resolved information may support training or mechanism analysis but must not be required at inference.

A fresh literature collision review shows that generic `multi-scale + multi-horizon` modeling is already crowded in EV charging forecasting (MFT, ATF-PatchTST, TCN-LSTM, multiple-time-scale expert systems, multi-step Autoformer variants). Generic knowledge distillation is also occupied, including `PhysDistill-EV` (IEEE Access, 2026). Therefore neither multi-scale encoding, Transformer/PatchTST/TCN choice, horizon conditioning nor knowledge distillation can be claimed as the contribution by itself.

The selected research direction is instead:

> **station-level multi-horizon core + session-resolved training-only auxiliary supervision**.

This uses standard Learning Using Privileged Information / multi-task principles to bridge data granularity: the model receives station-level inputs, while ACN session-resolved existing/arrival component truths may be used only as auxiliary training labels. The same model must run without session fields on station-level-only datasets.

## 6. Selected R11 structure

### R11-S0 — station-level deep-backbone screening

Purpose: choose a stable carrier architecture using only station-level predictors.

Candidate families for the protocol:

```text
GRU
TCN
N-HiTS
PatchTST   (strong modern control, not presumed final backbone)
```

Backbone choice is not a novelty claim. The protocol must match inputs, target rows, chronology and training budget as far as practical.

### R11-M1 — privileged auxiliary-supervision test

Only after R11-S0 identifies a stable core:

```text
Arm 1: total-load supervision only
Arm 2: same station-level inputs/backbone + training-only existing/arrival auxiliary supervision
```

The source-side auxiliary labels may be:

```text
E(t,h)  existing-session contribution
A(t,h)  future-arrival contribution
Y(t,h)  total station current
```

but `E/A`, requested departure, per-session current/pilot and other session fields are not required deployment inputs.

The scientific question is whether privileged fine-grained supervision improves the aggregate station-level representation and remains useful when inference sees aggregate data only.

## 7. Evidence and portability boundary

The four JPL development months remain method-development data. The final JPL holdout `2019-03/06/09/12` remains sealed.

A later portability test, if R11-M1 passes, must evaluate the same station-level model in a deployment setting where session information is hidden or unavailable. Do not select a target dataset after seeing favorable model results.

The current direction deliberately avoids tying the final algorithm to ACN session inputs.

## 8. Current prohibitions

Do not:

- open or prepare the JPL final holdout;
- rerun/tune R7 to repair R10;
- return to requested-departure feature/bin engineering as the prediction method;
- use future/session-resolved information as inference input;
- claim generic multi-scale modeling, Transformer, TCN, PatchTST, multi-horizon forecasting or knowledge distillation as novel by themselves;
- select favorable months/horizons/datasets after observing results;
- start R11 model fits before the R11-S0 protocol freezes common inputs, chronology, model budgets, metrics and selection/STOP rules.

R9 and R10 outcomes remain unchanged.

## 9. Immediate next action

The only authorized next task is **R11-S0 protocol design**. No local training command is authorized yet.

The protocol must freeze:

1. station-level-only feature contract;
2. history window and five fixed horizons;
3. development chronology and validation rule;
4. candidate backbone definitions;
5. comparable model/training budgets;
6. optimizer/seed/early-stopping policy;
7. headline accuracy and stability metrics;
8. backbone-selection and STOP rules;
9. exact prohibition on final-holdout access.

Once R11-S0 is frozen, implementation and one controlled development screening can be considered.
