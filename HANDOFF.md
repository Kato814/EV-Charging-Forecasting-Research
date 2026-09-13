# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R4-I0 protocol](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_PROTOCOL_20260913.md)、[post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md) 和 [R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md)。历史链再读 R2/R1/P1 outcomes 与 [EXPERIMENT_LEDGER](docs/EXPERIMENT_LEDGER.md)。

## 1. 当前科学状态

```text
S1 = MIXED_STRUCTURED_SIGNAL
P1 = STOP_MECHANISM_ROUTE, CLOSED
R1 = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2 = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = information-sufficiency / state-aliasing protocol frozen in current PR; NOT RUN
```

Final holdout `2019-03/06/09/12` 继续封存。当前**没有用户本机命令**。

## 2. 为什么进入 R4-I0

S1/P1/R1/R2/R3 已依次检验 future composition、explicit session mechanism、pairwise joint state、higher-order nonlinear session set、pilot-vs-actual control state。R3-C0 因 overall valid control-state support 仅0.36256触发 STOP；不能降低阈值 rescue。

Post-R3 screening 排除了 larger set/trajectory encoder、generic residual/ramp、peak forecasting、latent/censored demand、generic probabilistic EV forecasting、generic horizon MoE 和 similar-day selection作为当前新核心。

下一问题不是再换模型，而是：

> 在冻结合法 issue-time 状态下，历史中非常相似的状态是否仍对应 materially divergent future station current；完整 M3 state 是否能比简单 current-level analog 稳定选出未来更接近的历史状态？

这是 empirical state-aliasing / information-sufficiency gate，不是不可预测定理、kNN方法创新或概率预测创新。

## 3. Frozen R4-I0 state tiers

```text
Level-Control = fold-local M2 Ridge 标准化后的 station_current_a 单坐标
M2-State      = 完整 canonical M2，201 raw -> 204 encoded
M3-State      = 完整 canonical M3，311 raw -> 391 encoded
```

M3 primary rich-state arm；M2 secondary representation control；Level primary baseline。

使用仓库现有 `RidgePreprocessor`：historical-only median imputation、nullable indicators、mean/std standardization。禁止 PCA、metric learning、feature weights/selection、target supervision。

R4-I0 不 instantiate Ridge regression 或任何 estimator；model fit count 必须为0。

## 4. Frozen causal analog construction

每个 development month × local test day × horizon：

1. test rows 为冻结 OOS rows；
2. historical rows 只有在 issue time 早于 test-day midnight 且该 horizon label 已在 midnight 前可用时 eligible；
3. preprocessors 只 fit eligible historical rows；
4. 每个 test issue 的 candidate pool 只含同一 month、exact same `America/Los_Angeles` 15-min clock slot 的 eligible historical rows；
5. `MIN_CANDIDATES=10`；
6. `K=3` analogs；
7. future label/error 永不参与 matching。

Distances：

```text
Level: abs(z_station_current_i - z_station_current_j)
M2:    sqrt(mean((z_M2_i-z_M2_j)^2))
M3:    sqrt(mean((z_M3_i-z_M3_j)^2))
```

同距离 tie 由更早 issue time 打破。

## 5. Frozen similarity support

“相似”只用 M3 historical feature geometry 定义：

- same-clock candidate pool 内，每个历史 row 计算第三近邻 M3 distance；
- historical support threshold = 这些 third-NN distances 的 empirical q95，quantile method=`higher`；
- test third-NN M3 distance <= threshold 才 in-support。

同一 supported test set 用于 Level/M2/M3。

Support gate：

```text
pooled supported origin-horizon fraction >= 0.70
每个20个 month-horizon cell supported fraction >= 0.50
每个 cell supported records >= 250
```

Support fail => `STOP_STATE_ALIASING_ROUTE / INSUFFICIENT_ANALOG_SUPPORT`。结果后禁止改 K、same-clock window、candidate floor 或 q95 rule。

## 6. Frozen outcome divergence

Analog identities 固定后才使用 target labels：

```text
D_a(i,h) = mean_j |y(i,h)-y(j,h)|, j in 3 analogs
G_level = mean(D_level)
G_M2    = mean(D_M2)
G_M3    = mean(D_M3)
Y_scale = mean(abs(y))

skill_M3_vs_Level = 1 - G_M3/G_level
skill_M3_vs_M2    = 1 - G_M3/G_M2
skill_M2_vs_Level = 1 - G_M2/G_level
normalized_M3_divergence = G_M3/Y_scale
```

Positive skill 表示 richer state 选出的 historical analog future 更接近。

## 7. Frozen decisions

### PASS_STATE_ALIASING_SIGNAL

全部满足：support pass；pooled normalized M3 divergence>=0.10；>=3/5 horizons normalized divergence>=0.08；pooled M3-vs-Level skill<=0.05；pooled M3-vs-M2 skill<=0.02；只有<=1/5 horizons和<=1/4 months的 M3-vs-Level skill>=0.10；60-min skill<=0.05且normalized divergence>=0.10。

PASS只说明 frozen metric 下存在 material empirical aliasing，授权另行 uncertainty/external-information/target-design protocol；不自动开 holdout。

### STOP_STATE_ALIASING_ROUTE

Support pass 后满足任一：

A. pooled M3-vs-Level skill>=0.10，>=3/5 horizons和>=3/4 months skill>=0.05，且60-min>=0.05；

或 B. pooled normalized M3 divergence<0.05，且>=4/5 horizons<0.08。

含义：不支持当前 issue-time information insufficiency 解释。

其余 => `MIXED_STATE_ALIASING_SIGNAL`，只能做另行 preregistered read-only failure analysis。

## 8. Novelty boundary

不得声称 first EV predictability、first similar-state/kNN、first probabilistic EV forecasting。Applied Energy 2024已有用户级 charging predictability heterogeneity；Applied Energy 2026已有 similar-day EV load forecasting；DiffPLF/CUP-EV等覆盖概率多时距EV负荷预测。

R4-I0 的窄边界是：**在本项目连续 richer deterministic representations 失败后，对 frozen causal JPL issue-time state 做 preregistered empirical information-sufficiency/state-aliasing test。**

## 9. Current execution order

当前无本机动作。顺序必须是：

1. R4-I0 protocol PR full CI/review/merge；
2. 新建独立 zero-fit implementation PR；
3. tests 锁 causal eligibility、Ridge preprocessing、same-clock candidates、K=3、q95 support、distance/decision rules；
4. full pytest/compileall/Ruff；
5. CI通过后发布 pinned one-time launcher；
6. development-only run exactly once；
7. frozen PASS/MIXED/STOP 裁决。

禁止在 protocol merge 前实现/运行，禁止 target-informed matching、alternate K/time windows/PCA/metric learning/feature selection、新 deterministic backbone和 final holdout 访问。

## 10. Asset / runtime protection

保留所有历史 worktree、failed/complete status、private caches、R2/R3 outputs 和 `evcf-r2-set`；不 reset/clean/stash/force push。长任务 PowerShell 只输出 stage/month/horizon/coarse completed count/completion。代码通过、PR合并、本机运行完成、科学假设通过分别报告。