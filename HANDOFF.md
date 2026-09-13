# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管顺序：先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R4-I0 protocol](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_PROTOCOL_20260913.md)、[post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md)、[R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md)。历史链再读 R2/R1/P1 outcomes 与 [EXPERIMENT_LEDGER](docs/EXPERIMENT_LEDGER.md)。

## 1. 当前科学状态

```text
S1 = MIXED_STRUCTURED_SIGNAL
P1 = STOP_MECHANISM_ROUTE, CLOSED
R1 = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2 = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = information-sufficiency / state-aliasing protocol + implementation frozen; NOT RUN
```

Final holdout `2019-03/06/09/12` 继续封存。当前唯一授权本机动作是 pinned R4-I0 zero-fit launcher 首次 development-only 运行。

R3-C0 overall valid control-state support 仅 `0.3625615764`，正式 `STOP_CONTROL_ENDOGENEITY_ROUTE / INSUFFICIENT_CONTROL_STATE_SUPPORT`。有效子集虽然出现约7%的 pooled error contrast，但不能降低 support threshold rescue；而且 60-min 下 Equal 与 S1 同时维持 pooled 方向只有 2/4 months，因此不能把描述性关联提升为稳定 PASS 机制证据。

## 2. R4-I0 frozen question

不是再换 deterministic backbone，而是检验：在合法 issue-time state 已很相似时，future `station_current_mean_a` 是否仍明显分叉，以及完整 M2/M3 是否能比 simple current-level analog 稳定选出 future outcome 更接近的历史状态。

```text
Level-Control = fold-local M2 Ridge 标准化后的 station_current_a 单坐标
M2-State      = canonical M2, 201 raw -> 204 encoded
M3-State      = canonical M3, 311 raw -> 391 encoded
MIN_CANDIDATES = 10
K = 3
```

每个 month × local test day × horizon：历史候选只允许 label 已在 test-day midnight 前可用的 rows；`RidgePreprocessor` 仅 fit eligible history；候选只取同一 month、exact same America/Los_Angeles 15-min clock slot；future target/error 不参与 matching。Level distance 为 standardized current gap；M2/M3 为 encoded RMS Euclidean distance；ties 由更早 issue time 打破。

Support 只由 M3 historical geometry 定义：historical third-NN M3 distance 的 empirical q95（`higher`）为 threshold，test third-NN <= q95 才 in-support。同一 supported set 用于三组 analog。

```text
pooled supported fraction >= 0.70
每个20个 month-horizon cell supported fraction >= 0.50
每个 cell supported records >= 250
```

Support fail => `STOP_STATE_ALIASING_ROUTE / INSUFFICIENT_ANALOG_SUPPORT`。首次结果后禁止改 K、same-clock window、candidate floor、q95、metric、features 或 decision thresholds。

完整 `PASS_STATE_ALIASING_SIGNAL / MIXED_STATE_ALIASING_SIGNAL / STOP_STATE_ALIASING_ROUTE` 数值判据只以 frozen R4-I0 protocol 为准。PASS 也只表示 frozen metric 下的 empirical aliasing，不是 information-theoretic irreducibility，且不自动打开 final holdout。

## 3. Frozen code identity

```text
protocol PR                   #78
protocol merge                fec13c28cb5d4b2490256f8a26d82f45d8af6051
implementation PR             #79
implementation merge          58ebcb97869dc48ea0dfa5a7615134a5e822ac3b
pre-result reporting repair   #80
reviewed executable head      d3f00320e90aeb213d97d63d3460f58d495dd34a
reporting repair merge        1590b980b50e6ac1cb2db955b102431aa0c1ad25
```

PR #80 在任何 R4 outcome 产生前补齐冻结协议要求的 public distance-support summaries：candidate count、test third-neighbor M3 distance、historical q95 threshold 等。它不改变 causal eligibility、preprocessing、distance、support、divergence 或 PASS/MIXED/STOP。完整 pytest/compileall/Ruff 已通过。

## 4. Pinned launcher

```text
evcf_r4_i0_launcher_v1.py
SHA256 = 880a5221594b5434386d62ec1b242c915cf229802ddc5644f09b52f9ea82345e
expected reviewed head = d3f00320e90aeb213d97d63d3460f58d495dd34a
```

Launcher contract：development-only 2019-01/04/07/10；holdout paths blocked；frozen Python/packages；缺失 reviewed code 时只 fetch PR #80 head ref；detached exact-code worktree；development snapshots 与已有 worktree tracked state 前后校验；child environment 移除 `ACN_API_TOKEN`；不 reset/clean/stash/delete；不自动清理；public result 必须 `fit_count=0` 且 forbidden-action flags 全 false，并包含冻结 distance-support summaries。

运行结束后用户只上传最新 `evcf_r4_i0_status_*.json`。若 `INCOMPLETE`，先只读诊断，不重复大实验；若 `COMPLETE`，直接按 frozen PASS/MIXED/STOP 裁决，不改阈值。

## 5. 当前执行顺序

```text
1. protocol PR + CI/review/merge                         DONE
2. zero-fit implementation PR                            DONE
3. causal/preprocessing/candidate/support/decision tests DONE
4. full pytest / compileall / Ruff                       PASS
5. pre-result reporting repair + pinned launcher         DONE
6. development-only R4-I0 run exactly once               NEXT
7. frozen PASS/MIXED/STOP decision                       AFTER RUN
```

## 6. 资产与表达边界

保留全部历史 worktree、failed/complete status、private caches、R2/R3 outputs 与 `evcf-r2-set`；不 reset/clean/stash/force push。PowerShell 命令必须单行。代码通过、PR合并、本机运行完成、科学假设通过要分开报告。

不得声称 first EV predictability、first similar-state/kNN 或 first probabilistic EV forecasting。R4-I0 的窄边界是：在连续 richer deterministic representations 失败后，对 frozen causal JPL issue-time state 做 preregistered empirical information-sufficiency/state-aliasing test。