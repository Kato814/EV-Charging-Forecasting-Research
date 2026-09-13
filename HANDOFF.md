# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R3-C0 protocol](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_GATE_PROTOCOL_20260913.md)、[post-R2 screening](docs/JPL_POST_R2_METHOD_SCREENING_20260913.md) 与 [R2 outcome](docs/JPL_R2_HIGHER_ORDER_SESSION_SET_OUTCOME_20260913.md)。历史链再读 R1 outcome/diagnostic、P1 outcome 与 [EXPERIMENT_LEDGER](docs/EXPERIMENT_LEDGER.md)。

## 1. 当前科学状态

```text
S1 = MIXED_STRUCTURED_SIGNAL
P1 = STOP_MECHANISM_ROUTE, CLOSED
R1 = MIXED_JOINT_STATE_SIGNAL, diagnostic CLOSED
R2 = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = control-endogeneity 0-fit gate, protocol frozen in current docs PR, NOT RUN
```

Final holdout `2019-03/06/09/12` 继续封存。当前**没有用户本机命令**。

## 2. R2 已正式关闭

R2 protocol merge：`ab0b8f6b7521f9e55d65a82fe7d44140a0973fef`。

R2 implementation PR #71 reviewed head：`1ec7b02bb0e44353034aa86678ce039e747a589f`；merge：`b1093ab6580a5153346f6b8c4981b2d2ba20b51e`。

正式运行：550 fits，448.055812 s，RTX5080 / cuda:0 / PyTorch 2.14.0+cu132 / CUDA 13.2。

```text
Equal        28.9172859886 A
S1           28.5948815297 A
R1-Joint     29.0399775992 A
R2-Permuted  33.3294171470 A
R2-Joint     33.5660251919 A
```

R2-Joint 仅 2/5 horizons、1/4 months 胜 Permuted；pooled Joint > Permuted，因此冻结为 `STOP_HIGHER_ORDER_SET_ROUTE`。R2 private manifest：`9f35cffc192ebcebe30204fa1d23137ffc41e8ba858d9c55acfa85952d09bdd6`。

R2 outcome PR #74 merge：`154ff4c10d725f24e84955c5895ad74668029c9c`。

不要重跑 R2，不要换 permutation，不要扩大 Deep Sets，不要用 Set Transformer/attention/MoE rescue。R2 GPU 环境 `evcf-r2-set` 与 reviewed worktree继续保留。

## 3. 为什么转向 R3-C0

S1/P1/R1/R2 都把主要努力放在 session population / future composition 的表示上，但没有形成稳定实用优势。post-R2 screening 因此不再选“更大 backbone”。

ACN/JPL 的 realized current 同时受车辆需求和 EVSE pilot/current limit 影响，而未来 pilot/control path 并未作为现有 forecast-time predictor 提供。下一问题是：

> 在未来控制路径未知时，当前 pilot-versus-actual operating state 是否稳定标识未来 realized-current 的预测难度？

这是 data-generating-process / forecastability 问题。它不是“首次使用 pilot”，也不是因果识别。

## 4. R3-C0 冻结输入与状态

Development：`2019-01/04/07/10`。

Primary frozen refs：Equal、S1；R1-Joint secondary only。

合法 issue-time inputs：

```text
M3 current_current_a
M3 current_pilot_a
M2 station_current_a   # matching only
```

对一个 issue group：paired-valid row 需 actual/pilot finite 且 pilot>0。定义：

```text
C = sum(actual)
P = sum(pilot)
U = C/P
coverage = K/N
```

R3-C0 valid：`N>0`, `K>0`, `coverage>=0.80`, `P>=6A`, station_current finite, U finite。U 不 clipping。

Secondary only：`binding_fraction_90 = mean(actual >= 0.90*pilot)`。

## 5. Frozen matching / contrast

每月独立：

1. valid issue times 按 current station load 稳定排序；
2. rank 分5个等计数 current-level bins；
3. bin 内按 U 稳定排序并分 lower/upper halves；
4. odd bin 的单个中位 row 只进 support，不进 contrast；
5. lower/upper 各自再按 station current 排序，按 rank 配对；
6. 同一 month-level pairs 复用于所有 horizons/models。

匹配禁止读取 truth/error。

对 matched pair：

```text
d = abs(pred_low-truth_low) - abs(pred_high-truth_high)
b = (AE_low+AE_high)/2
delta_fraction = mean(d)/mean(b)
```

正值表示 lower-U 更难预测；负值表示 higher-U 更难预测。方向不预设。

## 6. Frozen support / decision

Support 必须全部满足：

```text
overall valid_issue_fraction >= 0.70
every month valid_issue_fraction >= 0.50
every month matched pairs >= 100
```

PASS `PASS_CONTROL_ENDOGENEITY_SIGNAL` 要求：Equal/S1 pooled |delta_fraction| 均>=5%，同号；二者各自 >=3/5 horizon 与 >=3/4 month 保持 pooled 方向；60 min 时两 reference 在>=3/4月与 pooled 方向一致。

MIXED 要求：support pass、Equal/S1 pooled 同号；至少一者 pooled |delta|>=3%；两者各自 >=2/5 horizons、>=2/4 months 保持该方向，但 PASS 未全满足。

STOP：support fail；或 Equal/S1 pooled 异号/任一为0；或二者 pooled |delta| 都<3%；或任一 reference 方向一致性 <=1/5 horizons 或 <=1/4 months。

PASS 只授权另行冻结 modeling/target-design stage；不直接训练，不开 holdout。MIXED 只允许另行 scoped read-only diagnostic。STOP 关闭 control-endogeneity route。

## 7. 当前执行顺序

当前无本机动作。顺序必须是：

1. 合并 post-R2 screening + R3-C0 protocol docs PR；
2. 新建独立 R3-C0 implementation PR；
3. 实现**0-fit read-only** gate、reference/cache identity、holdout fail-closed、matching/decision tests；
4. full pytest/compileall/Ruff；
5. CI/审查通过后才发布一次 pinned launcher；
6. development-only 运行一次；
7. 按预注册规则裁决。

禁止：模型 fitting/retraining、future pilot path、阈值/5 bins/U formula 事后调整、删日期/小时/时距、clipping/calibration、P1/R1/R2 rescue、Set Transformer/MoE/trajectory model。

## 8. 运行与资产保护

保留全部历史 worktree、failed/complete status、private caches、R2 private output 和 `evcf-r2-set`。不 reset/clean/stash/force push。

后续耗时脚本按用户最新要求，只输出：**stage / month / horizon / coarse completed count / completion**。不要再输出每5 epoch等高频训练日志。PowerShell 命令必须单行。

代码通过、PR合并、本机运行完成、科学假设通过必须分别报告。