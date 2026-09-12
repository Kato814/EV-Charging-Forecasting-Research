# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R2 protocol](docs/JPL_R2_HIGHER_ORDER_SESSION_SET_PROTOCOL_20260912.md)、[post-R1 screening](docs/JPL_POST_R1_METHOD_SCREENING_20260912.md)，再读 [R1 diagnostic outcome](docs/JPL_R1_MIXED_DIAGNOSTIC_OUTCOME_20260912.md)、[R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md) 和 [实验台账](docs/EXPERIMENT_LEDGER.md)。

## 1. 当前科学状态

```text
S1 = MIXED_STRUCTURED_SIGNAL
P1 = STOP_MECHANISM_ROUTE, CLOSED
R1 = MIXED_JOINT_STATE_SIGNAL, diagnostic CLOSED
R2 = protocol frozen, implementation/training NOT STARTED
```

R1 原训练和后续只读诊断都已完成，不要再次要求用户运行身份预检、R1 launcher、550 次 R1 fit 或同一日级/小时级统计。R1 诊断已通过 PR #69 收口，merge `7c8c07fcce1409283b9764616d9f7811056f6d99`。

Final holdout 2019-03/06/09/12 继续封存。

## 2. 为什么进入 R2

R1 的 55 个 pairwise Pearson joint features 在 matched Control 上有小幅 pooled 增益，但未稳定超过 Equal/S1。最终诊断说明：

- 七月 joint 增量退化分布在多个日期，不是单一异常点；
- 十月存在真实 Joint-vs-Control 收益，但仍有对 Equal 的残余差距；
- 60 min 的总体优势只有 0.055223 A，07:00/09:00 跨月方向不稳；
- 不能通过删日期、筛 pair、换相关估计器或时间门控 rescue R1。

因此下一问题不是换更大 backbone，而是验证 Pearson 没覆盖的**高阶同会话联合结构**。

## 3. R2 核心设计

科学问题：

> 在每个字段的边际值、缺失模式、会话数和 station context 完全相同的条件下，真实 same-session tuple alignment 是否能稳定提升 aggregate multi-horizon station-current forecast？

Matched arms：

### R2-Joint

- exact frozen M2 raw context；
- issue time 已连接 session 的真实 11-field tuple set；
- 每字段 numeric + observed bit，共 22 维 session element；
- 小 Deep-Sets-style shared encoder + sum pooling；
- 直接预测 `station_current_mean_a`。

### R2-Permuted

- M2 context 相同；
- session 数相同；
- 每个字段的值 multiset 和 missing/observed multiset 完全相同；
- 仅在同一 issue 内对每个字段独立、确定性地跨 session 置乱，从而破坏真实 cross-field tuple alignment；
- 与 Joint 使用相同网络、参数量、preprocessing、fold、初始化、batch 顺序和 optimizer。

置乱固定为：先按 private `anonymous_session_index` 建 canonical order（ID 不进入模型/公开输出），再按 `R2_PERMUTED_V1|20260912|issue_utc|field_index` 的 SHA256 派生 PCG64 seed。不能结果后改 permutation 或多次搜索控制组。

## 4. R2 合法输入

M2 raw width = 201；沿用 canonical names/order/nullable mask。fold-local 标准化后只增加固定 3 个 M2 nullable indicators，context width = 204。

Session fields 固定为：

1. elapsed_connection_s
2. elapsed_charging_time_proxy_s
3. current_current_a
4. recent_current_mean_a
5. recent_current_peak_a
6. recent_current_observed_ratio
7. cumulative_current_ah
8. cumulative_current_observed_ratio
9. current_pilot_a
10. requested_departure_minutes_from_issue
11. known_kwh_requested

`anonymous_session_index` 仅内部 canonicalization。禁止 session ID predictor、future current、future arrival、realized departure、future composition、final delivered kWh、test error/offline anomaly 等未来信息。

## 5. 固定网络/优化

```text
session phi: 22 -> 32 -> 32, ReLU
pool: sum
M2 context: 204 -> 64 -> 32, ReLU
head: 64 -> 32 -> 1
weights: Xavier uniform; bias=0
```

五个 horizon 独立模型，无 horizon token/query/gate。

```text
loss = L1Loss
AdamW
lr = 1e-3
weight_decay = 1e-4
batch = 256
epochs = 30
no early stopping
no scheduler
no dropout
float32
no AMP
no torch.compile
no clipping/calibration
```

每个 fold/horizon Joint 与 Permuted 使用同一确定性模型 seed 与 batch order。正式 rolling-origin 继续采用原 development expert 的同月日级 OOS 因果规则。

## 6. 冻结判据

Primary: `R2-Joint vs R2-Permuted`。

Required external references: M2 / M3 / Equal / S1 / R1-Joint，全部复用冻结 cache，不重训。

### PASS_HIGHER_ORDER_SET_SIGNAL

全部满足：

1. pooled Joint < Permuted；
2. pooled Joint < Equal；
3. pooled Joint < S1；
4. pooled Joint < R1-Joint；
5. Joint vs Permuted horizon wins >=3/5；
6. Joint vs Permuted month wins >=3/4；
7. Joint vs Equal horizon wins >=3/5；
8. Joint vs Equal month wins >=3/4；
9. Joint vs S1 horizon wins >=3/5；
10. Joint vs S1 month wins >=3/4；
11. 60-min Joint < Equal；
12. 每个 horizon 相对 `min(Equal,S1)` 的退化不超过5%。

PASS 只允许另行冻结 seed-robustness / method-freeze，不自动开放 holdout。

### MIXED_HIGHER_ORDER_SET_SIGNAL

pooled Joint < Permuted，且 vs Permuted 至少 2/5 horizon、2/4 month 获胜，但 PASS 未全满足。只能做失败分析，不上更大网络。

### STOP_HIGHER_ORDER_SET_ROUTE

任一成立：pooled Joint >= Permuted；或 vs Permuted horizon wins <=1/5；或 month wins <=1/4。关闭当前 higher-order set 路线，不用 Set Transformer/MoE rescue。

## 7. Novelty boundary

已碰撞的直接 prior art：

- Deep Sets / Set Transformer：permutation-invariant set architecture 已成熟；
- Kwon & Zhu HICSS 2022：EVCS variable-size EV state aggregation；
- Berkeley `StationLevelPowerForecasting`：active-session features 用于 station-level forecast；
- SessionFlow 2026：origin-active continuation + future served-session generation + station aggregation；
- 2026 多种 TFT/MFT/MoE/spatiotemporal EV forecasting。

所以不能声称 first active-session、first variable-set、first Deep Sets EV、first session-aware、first horizon-specific、first existing/future decomposition。

R2 当前真正可检验的贡献边界：**marginal-preserving counterfactual 下，高阶 origin-active same-session joint state 的 predictive value。**

## 8. GPU / 环境

不要修改已接受的 `evcf-gate1-pilot`。

R2 正式环境目标：

```text
evcf-r2-set
Python 3.11.16
PyTorch 2.14.0
CUDA cu132
cuda:0 = NVIDIA GeForce RTX 5080
```

正式 fit 前必须单独通过 environment/GPU preflight：exact package pins、`torch.cuda.is_available()`、设备名、float32 forward/backward smoke test。若 5080/CUDA 条件不满足则 fail-closed，不静默 CPU fallback。CI 可以 CPU 单测，但不是正式实验。

用户要求的运行体验是固定约束：耗时脚本实时 flush，显示 device、month、horizon、arm、fit/day、粗粒度 epoch（至少每5 epochs）与 elapsed time；PowerShell 单行。

## 9. 当前唯一下一步

当前**没有用户本机命令**。

顺序必须是：

1. R2 screening/protocol PR 全量 CI + 审查 + merge；
2. 新建独立 R2 implementation branch；
3. 实现 matched Joint/Permuted、回归测试、holdout fail-closed、GPU preflight；
4. implementation PR 全量 CI；
5. 创建独立 `evcf-r2-set` 环境并验证 RTX5080；
6. 仅在以上全部通过后发布 pinned launcher；
7. development-only 运行一次；
8. 按预注册判据裁决。

禁止在协议未合并时训练、下载新数据、访问 final holdout、调 R1/P1、筛日期/pair、启用 Set Transformer/MoE/TPP。

## 10. 资产保护

保留所有历史 worktree、failed/complete status、private cache、diagnostic outputs；不 reset/clean/stash/force push。raw/interim/processed、row/session predictions、model weights、private IDs、凭据和绝对路径不进 Git。
