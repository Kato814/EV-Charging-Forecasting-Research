# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，论文可行性判断见 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)，R11 算法方向见 [R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)，冻结协议见 [R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)，实现交接见 [R11-S0 implementation handoff](docs/JPL_R11_S0_IMPLEMENTATION_HANDOFF_20260915.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE。R11-S0 protocol / implementation / review / CI / pinned launcher 已冻结，正式 68-fit 本机运行尚未执行。final holdout 2019-03/06/09/12 继续封存。**

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

R9 已永久关闭进一步 departure-representation refinement；R10 不改变该结论，也不授权 final holdout。

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

当前主线是 **portable station-level deep forecasting**。最低部署输入合同为：

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

选定的后续科学假设仍是：

> **station-level multi-horizon core + session-resolved training-only auxiliary supervision**。

R11-S0 只负责选择稳定的 station-level backbone；真正的 privileged-supervision 假设将在后续 R11-M1 中单独预注册验证。

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

## 5. R11-S0 implementation identity

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
final CI workflow run     34930090477
final CI                  pytest PASS / compileall PASS / Ruff PASS
```

Shape-only parameter counts：

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

全部位于 frozen `50k–250k` 参数带内，因此未发生 width correction。

## 6. Pinned launcher

External pinned launcher：

```text
filename  evcf_r11_s0_launcher_v1.py
SHA256    c732aac69e8dee1ca6c7d6e76138a78821f7f491c59bf7ee627fcf8cf534e2f4
```

Formal preflight 要求：

```text
Python 3.11.x
PyTorch 2.14.0
CUDA 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32 only
CUBLAS_WORKSPACE_CONFIG=:4096:8
```

launcher 会先 preflight，只有 PASS 后才进入任何 fit；无 CPU fallback。它固定 reviewed executable、protocol/config blob、merge ancestry，并在 detached preserved worktree 中运行，不自动清理。

## 7. Frozen R11-S0 decision

Deep candidate 进入 R11-M1 的 eligibility：

```text
pooled median MAE <= 1.02 * Station-HGB
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four folds complete
```

三类 exhaustive result：

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

若多个 eligible，按 pooled median MAE 最低选择；top-2 差异 `<0.25%` 时选参数更少者。不得看结果后添加第五模型、额外 seed、Mamba/SSM、ensemble、clipping 或 calibration。

## 8. Current execution state

```text
R11-S0 formal run        NOT RUN
R11-S0 formal fit_count  0
final holdout accessed   false
session predictors used  false
```

实现、shape preflight、code review 与 CI 均没有进行 JPL real-label R11-S0 fitting。

## 9. Immediate next action

**现在唯一授权的下一步是用户本机使用 pinned launcher 执行一次正式 R11-S0。**

launcher 完成后，无论 `COMPLETE` 还是 `INCOMPLETE`，只上传最新：

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

若为 `INCOMPLETE`，先审 status，不自行改代码、环境或重跑；若为 `COMPLETE`，先按冻结 SELECT/MIXED/STOP 规则审计，再决定是否有资格设计 R11-M1。

Final JPL holdout `2019-03/06/09/12` 在任何 R11-S0 结果下都继续封存。
