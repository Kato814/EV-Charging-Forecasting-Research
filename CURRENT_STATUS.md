# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R11-S0 正式结果见 `docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`；R11-P1 冻结协议见 `docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md`；R11-P1 结果见 `docs/JPL_R11_P1_PRIVILEGED_ARRIVAL_OUTCOME_20260915.md`。

**当前科学状态：R11-P1 已 COMPLETE，44/44 fits 完成，冻结判定为 `MIXED_PRIVILEGED_ARRIVAL_SIGNAL`。未来到达 training-only 辅助监督在 3/3 长时距、4/4 开发月份、3/3 paired seeds 上均改善同一 station-only TCN，但 Arm C seed spread 为 4.8494%，超过冻结 3% 门槛。Final holdout 2019-03/06/09/12 仍未访问。**

## 1. Closed stages

```text
R10-R0      COMPLETE / MIXED_DEVELOPMENT_ROBUSTNESS
R11-S0      COMPLETE / STOP_DEEP_CORE_ROUTE / 68 fits
R11-M1      CANCELLED
R11-P1      COMPLETE / MIXED_PRIVILEGED_ARRIVAL_SIGNAL / 44 fits
final holdout  SEALED
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

## 6. Next action

Do **not** rescue R11-P1 inside the same development protocol.

Preferred next stage is a separately frozen **independent-generalization experiment** that keeps the R11-P1 method unchanged and asks whether the C-B gain transfers to an independent session-rich source/site while deployment remains aggregate-only.

Priority:

```text
1. identify suitable independent site/source;
2. freeze data identity, chronology, exact Arm B/C method, seeds and decision rule before fitting;
3. run paired B/C without tuning lambda or architecture;
4. evaluate transfer and seed stability;
5. keep JPL final holdout sealed until a final confirmation protocol is justified.
```

If no suitable independent session-rich source is available, stop at development-stage evidence rather than tune the current JPL result further.
