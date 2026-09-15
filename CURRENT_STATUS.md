# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，论文可行性判断见 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)，R11 算法方向见 [R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)，冻结协议见 [R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)，原实现交接见 [R11-S0 implementation handoff](docs/JPL_R11_S0_IMPLEMENTATION_HANDOFF_20260915.md)，平行实现边界见 [authority/quarantine note](docs/JPL_R11_S0_AUTHORITY_QUARANTINE_NOTE_20260915.md)，第一次正式尝试及修复见 [pre-fit integrity repair](docs/JPL_R11_S0_PREFIT_INTEGRITY_REPAIR_20260915.md)。

**R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE。R11-S0 科学协议不变。第一次 formal attempt 在任何 fit 完成前因 `IMPLEMENTATION_DRIFT` fail-closed；本机 RTX 5080 / PyTorch 2.14.0+cu132 / CUDA 13.2 preflight PASS；`fit_count=0`、holdout=false。窄修复 PR #105 已通过完整 CI 并冻结；当前唯一授权执行身份为 repaired executable + launcher v1.2。PR #104 仍为 non-authoritative 平行实现。final holdout 2019-03/06/09/12 继续封存。**

## 1. Closed R7 line

R7 `Departure-Aug / TotalDeparture` 仍是旧 structured line 的 accepted development candidate：

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R9 已永久关闭 further departure-representation refinement；R10 不改变该结论，也不授权 final holdout。

## 2. R10-R0 frozen result

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
```

R10 的 READY 唯一失败项是 local-day win rate vs S1：`26/55 = 47.27% < 50%`。该结果不得通过事后调参修复。

## 3. R11 research objective

当前主线是 **portable station-level deep forecasting**。最低部署输入合同：

```text
required at inference
- station-level historical load/current
- timestamp/calendar context

not required at inference
- session IDs
- requested departure / requested energy
- per-session pilot/current
- existing/arrival truth labels
- realized future sessions
```

后续科学假设仍是：

> **station-level multi-horizon core + session-resolved training-only auxiliary supervision**。

R11-S0 只负责选择稳定 station-level backbone；真正 privileged-supervision 假设将在 R11-M1 单独预注册验证。

## 4. R11-S0 frozen protocol

Station-only input：

```text
24 h history = 96 x 15-min bins
channels     = standardized aggregate station current + validity mask
context      = issue/target timestamp calendar features
horizons     = 15 / 30 / 60 / 120 / 240 min
```

候选：

```text
GRU      2 layers, hidden 96
TCN      5 causal residual blocks, dilations 1/2/4/8/16
N-HiTS   3 hierarchical stacks, pooling 1/4/16
PatchTST patch 16 / stride 8 / d_model 64 / 2 layers
Station-HGB same-information anchor
```

Chronology：earlier development months + current days 1–14 train；current days 15–17 validate；current day >=18 为 exact frozen formal test origins。

Frozen test identity：

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

Formal fit ceiling：

```text
48 deep fits + 20 Station-HGB fits = 68 fits
```

## 5. Original authoritative implementation and first failed attempt

Original reviewed implementation：

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
```

Shape-only parameter counts：

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

First formal attempt with launcher v1.1：

```text
status file       evcf_r11_s0_status_20260915T061213Z.json
status SHA256     f29049799cf1536b514d0b20464b30d057224204a6151428fbed437ddd40cd1e
status            INCOMPLETE
reason            IMPLEMENTATION_DRIFT
fit_count         0
holdout accessed  false
GPU preflight     PASS
```

Root cause was raw-byte implementation identity checking across Git text normalization, not model/data/result failure. No completed fit occurred, so no R11-S0 performance result was observed.

## 6. Frozen pre-fit integrity repair

Only the implementation identity verifier was repaired. Scientific protocol is unchanged.

```text
repair PR                    #105
reviewed repaired executable 2107795e817bb8f2b490b98ed78f663f685306c8
repair implementation merge  384ff65f36c78bcc3cb89aed9e08ade1b5f12260
final repair CI run           34940555171
final repair CI               1264 passed, 4 skipped; compileall PASS; Ruff PASS
```

The repaired verifier requires exact HEAD identity plus Git-normalized clean diffs for every authoritative runtime path. Regression tests confirm CRLF/LF normalization is accepted while semantic content drift still fails closed.

## 7. Parallel implementation quarantine

A second R11-S0 implementation was previously merged through：

```text
PR #104 head    6688f9c631b9f03a8f1a995bab913141cedf9905
merge to main   2433e76b0d1ab3f1d1bfa8feb2cae42bd782ae57
```

This path remains **non-authoritative for scientific execution**. Its unprefixed `r11_s0_*` modules/scripts must not be mixed with the repaired PR #105 execution line. Historical evidence is preserved；no reset/force-push/deletion。

## 8. Sole authorized replacement launcher v1.2

```text
filename  evcf_r11_s0_launcher_v1_2.py
SHA256    c990a5dced70a75ac5c5b48615363fdb0e694fc19902d8c58ef13a573f2e7724
schema    evcf-r11-s0-launcher/v1.2
```

Formal preflight remains：

```text
Python 3.11.x
PyTorch 2.14.0
CUDA 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32 only
CUBLAS_WORKSPACE_CONFIG=:4096:8
```

v1.2 checks out repaired executable `2107795e817bb8f2b490b98ed78f663f685306c8` in a detached preserved worktree, verifies repair-merge ancestry, frozen protocol/config Git blobs, development manifest identities, holdout absence and environment before fitting. No CPU fallback or automatic cleanup。

## 9. Frozen R11-S0 decision

Deep candidate eligibility：

```text
pooled median MAE <= 1.02 * Station-HGB
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four folds complete
```

Exhaustive outcomes：

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

若多个 eligible，按 pooled median MAE 最低选择；top-2 差异 `<0.25%` 时选参数更少者。不得结果后添加第五模型、额外 seed、Mamba/SSM、ensemble、clipping 或 calibration。

## 10. Current execution state

```text
first formal attempt          INCOMPLETE pre-fit
completed R11-S0 fits         0
scientific R11-S0 result      NONE
replacement formal run        NOT RUN
final holdout accessed        false
session predictors used       false
```

## 11. Immediate next action

**唯一授权下一步：用户本机使用 exact v1.2 launcher 执行一次 replacement formal R11-S0。**

Before execution verify：

```text
evcf_r11_s0_launcher_v1_2.py
SHA256 = c990a5dced70a75ac5c5b48615363fdb0e694fc19902d8c58ef13a573f2e7724
```

运行结束后，无论 `COMPLETE` 或 `INCOMPLETE`，只上传最新：

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

若 `INCOMPLETE`，不自行改代码、环境或重跑；若 `COMPLETE`，先按冻结 SELECT/MIXED/STOP 规则审计，再决定是否设计 R11-M1。

Final JPL holdout `2019-03/06/09/12` 在任何 R11-S0 结果下都继续封存。
