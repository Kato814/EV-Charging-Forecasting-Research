# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R11-S0 正式结果见 `docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`；R11-P1 冻结协议见 `docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md`；R11-P1 结果见 `docs/JPL_R11_P1_PRIVILEGED_ARRIVAL_OUTCOME_20260915.md`；独立复现实验协议见 `docs/JPL_R11_G0_CALTECH_INDEPENDENT_REPLICATION_PROTOCOL_20260915.md`。

**当前科学状态：R11-P1 已 COMPLETE，44/44 fits 完成，冻结判定为 `MIXED_PRIVILEGED_ARRIVAL_SIGNAL`。Future-arrival training-only 辅助监督在 3/3 长时距、4/4 开发月份、3/3 paired seeds 上均改善同一 station-only TCN，但 Arm C seed spread 为 4.8494%，超过冻结 3% 门槛。新的 R11-G0 Caltech 独立站点复现协议已冻结，尚未采集正式 Caltech 数据、尚未拟合。JPL final holdout 2019-03/06/09/12 仍未访问。**

## 1. Closed stages

```text
R10-R0      COMPLETE / MIXED_DEVELOPMENT_ROBUSTNESS
R11-S0      COMPLETE / STOP_DEEP_CORE_ROUTE / 68 fits
R11-M1      CANCELLED
R11-P1      COMPLETE / MIXED_PRIVILEGED_ARRIVAL_SIGNAL / 44 fits
R11-G0      PROTOCOL FROZEN / NOT RUN
JPL final holdout  SEALED
```

R11-S0 不允许再加入第五模型、额外 seed、阈值放宽、clipping/calibration 或重跑。

R11-P1 不允许在原协议内调 lambda、增加 seed、改 30/60 min 分界、增加 backbone 或把 MIXED 改写成 PASS。

## 2. R11-P1 execution identity

```text
candidate PR            #110
candidate code commit   187c047596dffb74cef8a79fcc479edd55139d5f
launcher schema         evcf-r11-p1-candidate-launcher/v0.1
launcher SHA256         a9655dba0de6a54ea52c39171e392533d8b5c5e2c6ce52e9e1c5656435c33c31
deep fits               24 / 24
Station-HGB replay      20 / 20
total fits              44 / 44
holdout accessed        false
session predictors      false
```

Formal local environment:

```text
NVIDIA GeForce RTX 5080
PyTorch 2.14.0+cu132
CUDA 13.2
deterministic CUDA backward smoke PASS
```

GitHub Actions 当前月度 2,000 min 额度已耗尽，因此 repository-wide CI 暂不可用；这属于基础设施额度限制，不代表代码测试失败。额度重置后仅对稳定归档版本补跑完整 CI。

## 3. Frozen R11-P1 method

```text
15 / 30 min       -> Station-HGB
60 / 120 / 240    -> station-only TCN

Arm B: L = L_total
Arm C: L = L_total + 0.5 * L_future_arrival
```

Future-arrival session-resolved label 仅用于训练。推理阶段仍禁止 session ID、requested departure/energy、per-session pilot/current、future sessions 等信息。

## 4. R11-P1 result

Median pooled long-horizon MAE:

```text
Arm B  33.2304292334 A
Arm C  32.6842326626 A
C vs B improvement = 1.6437%
```

By horizon:

```text
60 min   26.9351872948 -> 25.8469801698 A   +4.0401%
120 min  33.2106616574 -> 32.2371871698 A   +2.9312%
240 min  40.5350216869 -> 40.4431764306 A   +0.2266%
```

Arm C wins `3/3` long horizons.

By month:

```text
2019-01  +2.7444%
2019-04  +0.4393%
2019-07  +1.4866%
2019-10  +3.3434%
```

Arm C wins `4/4` development months.

Paired seeds:

```text
2026091401  +0.6004%
2026091402  +0.9315%
2026091403  +1.9315%
```

Arm C wins `3/3` paired seeds.

Absolute comparison:

```text
Station-HGB long pooled       33.5592843062 A
Arm C long pooled             32.6842326626 A   +2.6075%

Station-HGB all-5 pooled      25.8731522189 A
Arm C hybrid all-5 pooled     25.3481212328 A   +2.0293%
```

## 5. Why MIXED

Only one frozen PASS gate fails:

```text
Arm B seed spread  4.8547%
Arm C seed spread  4.8494%   > 3.0% threshold
```

Because both arms have almost identical seed spread while C improves B under every frozen seed, horizon and month, the privileged label is not the obvious source of instability. The compact TCN carrier itself remains insufficiently seed-stable.

Scientific interpretation:

> training-only future-arrival supervision shows a consistent mechanism-aligned development signal, but algorithmic robustness is not yet strong enough for PASS.

## 6. Frozen R11-G0 independent replication

Independent site:

```text
ACN-Data site_id = caltech
formal months = 2019-02 / 2019-05 / 2019-08 / 2019-11
formal source = official ACN-Data /sessions/caltech/ts
```

These months are fixed before formal Caltech acquisition/fitting. They are complementary to both JPL development months and the sealed JPL holdout months.

R11-G0 copies the R11-P1 method unchanged:

```text
15/30 min       Station-HGB with frozen JPL-selected HGB hyperparameters
60/120/240 min  same station-only TCN
Arm B           L_total
Arm C           L_total + 0.5 * L_future_arrival
seeds           2026091401 / 02 / 03
fit ceiling     24 deep + 20 HGB replay = 44
```

No Caltech-specific architecture tuning, lambda tuning, HGB retuning, extra seed, clipping, calibration, ensemble or horizon-boundary search is allowed.

Before any model fit, acquisition/preprocessing must produce and freeze an aggregate-only Caltech data manifest with exact processed snapshot hashes and common formal row counts.

Frozen outcomes:

```text
REPLICATE_PRIVILEGED_ARRIVAL_SIGNAL
MIXED_INDEPENDENT_REPLICATION
FAIL_INDEPENDENT_REPLICATION
```

The quantitative replication gates are identical to R11-P1, including the `<=3%` seed-spread requirement.

## 7. Next action

Next authorized work is **Caltech acquisition/preprocessing implementation and pre-fit row-manifest generation only**.

Do not fit Arm B/C yet.

Execution order:

```text
1. implement site-general Caltech acquisition/preprocessing without changing JPL evidence;
2. locally acquire 2019-02/05/08/11 from official ACN-Data API;
3. run pre-fit QA and freeze processed snapshot/common-row manifest;
4. review the manifest for data-integrity completeness only;
5. only then authorize the 44-fit R11-G0 model run.
```

JPL final holdout remains sealed throughout R11-G0.
