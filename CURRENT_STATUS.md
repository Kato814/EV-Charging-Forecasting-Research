# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 `docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md`；R11 方向见 `docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md`；R11-S0 冻结协议见 `docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`；两次 pre-fit 修复分别见 `docs/JPL_R11_S0_PREFIT_INTEGRITY_REPAIR_20260915.md` 与 `docs/JPL_R11_S0_LABEL_READER_REPAIR_20260915.md`。

**当前科学状态：R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE。R11-S0 科学协议未改变。前两次 formal attempt 均在任何 fit 完成前 fail-closed：v1.1=`IMPLEMENTATION_DRIFT`，v1.2=`LABEL_INVALID`；两次均 `fit_count=0`、holdout=false。第二次失败根因为历史 base label reader 错把 JSON 对象键顺序当作语义；已通过 PR #106 复用既有 accepted order-insensitive compatibility reader 修复。当前唯一授权执行身份为 PR #106 reviewed executable + launcher v1.3。final holdout 2019-03/06/09/12 继续封存。**

## 1. R11 research objective

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

R11-S0 只负责选择稳定 station-level backbone；R11-M1 才验证 privileged-supervision 假设。

## 2. R11-S0 frozen protocol

```text
target              station_current_mean_a (A)
development months  2019-01 / 2019-04 / 2019-07 / 2019-10
history              96 x 15-min bins = 24 h
channels             standardized aggregate current + validity mask
horizons             15 / 30 / 60 / 120 / 240 min
```

Candidates：

```text
GRU      2 layers / hidden 96
TCN      5 causal residual blocks / dilations 1,2,4,8,16
N-HiTS   3 stacks / pooling 1,4,16
PatchTST patch16 / stride8 / d_model64 / 2 layers
Station-HGB same-information anchor
```

Chronology：

```text
train      all earlier dev months + current days 1-14
validation current days 15-17
test       current day >=18, exact frozen origins only
```

Frozen formal test origins：

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

Formal fit ceiling：

```text
48 deep + 20 Station-HGB = 68 fits
```

## 3. Formal environment and parameter counts

User-machine preflight has passed twice:

```text
GPU       NVIDIA GeForce RTX 5080 / cuda:0
PyTorch   2.14.0+cu132
CUDA      13.2
float32   smoke PASS
```

Frozen parameter counts：

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

## 4. Pre-fit attempt history

### Attempt 1 — launcher v1.1

```text
status file       evcf_r11_s0_status_20260915T061213Z.json
status SHA256     f29049799cf1536b514d0b20464b30d057224204a6151428fbed437ddd40cd1e
status            INCOMPLETE
reason            IMPLEMENTATION_DRIFT
fit_count         0
holdout accessed  false
```

Root cause：raw working-tree byte comparison was not portable across Git text normalization. Repaired by PR #105 using exact HEAD + Git-normalized clean diff semantics.

### Attempt 2 — launcher v1.2

```text
status file       evcf_r11_s0_status_20260915T102447Z.json
status SHA256     9b3d3570ba33c96c24cdef094b0bcdeeeefd7e29a5179958b15b85e1f9d8eb60
status            INCOMPLETE
reason            LABEL_INVALID
fit_count         0
holdout accessed  false
```

Root cause：accepted development snapshots serialize JSON with `sort_keys=True`; historical base reader incorrectly required insertion order of horizon keys to equal numerical horizon order. The already-existing compatibility reader validates the exact key set and reads values in frozen order `15/30/60/120/240`. R11-S0 had imported the historical base reader directly. No label value, target, row, horizon or split was wrong or changed.

## 5. Current authoritative repaired execution identity

Second pre-fit repair：

```text
repair PR                    #106
reviewed repaired executable 6ec9d690bbeb4b5dbe078daf42b52a6549eb14c9
repair implementation merge  da8989d16668bcf806e0e5efce2eabe52ec7b837
final repair CI run           34958616708
final repair CI               PASS
```

Repair scope：process-locally install the previously accepted order-insensitive frozen-label loader and bind that compatibility module into formal runtime identity. No architecture, feature, chronology, optimizer, seed, fit ceiling, metric, decision threshold, holdout rule or session-information boundary changed.

PR #104 remains a parallel **non-authoritative** implementation artifact and must not be used for formal execution.

## 6. Sole authorized launcher v1.3

```text
filename  evcf_r11_s0_launcher_v1_3.py
SHA256    da9824d472f6dc3541babab8aad001837a0cc1437504f8f2e0a3610059f031c1
schema    evcf-r11-s0-launcher/v1.3
```

v1.1 and v1.2 are retired for execution but preserved as evidence. v1.3 checks out reviewed executable `6ec9d690bbeb4b5dbe078daf42b52a6549eb14c9` in a detached preserved worktree, verifies merge ancestry, frozen protocol/config Git blobs, development manifests, holdout absence and formal environment before any fit. No CPU fallback or automatic cleanup.

## 7. Frozen R11-S0 decision and next action

Eligibility：

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

Current state：

```text
completed R11-S0 fits       0
scientific R11-S0 result    NONE
v1.3 formal run             NOT RUN
final holdout accessed      false
session predictors used     false
```

**唯一授权下一步：用户本机核验 exact v1.3 launcher SHA 后执行一次 replacement formal R11-S0。**

运行结束后，无论 `COMPLETE` 或 `INCOMPLETE`，只上传最新 `evcf_r11_s0_status_*.json`。若 `INCOMPLETE`，不自行改代码、环境或重跑；若 `COMPLETE`，先按冻结 SELECT/MIXED/STOP 规则审计，再决定是否设计 R11-M1。

Final JPL holdout `2019-03/06/09/12` 在任何 R11-S0 结果下都继续封存。
