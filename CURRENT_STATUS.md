# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1 结果见 [R4-D1 outcome](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_OUTCOME_20260913.md)；R4-D2 冻结协议见 [R4-D2 protocol](docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 均已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。R4-D1 已 COMPLETE；formal R4 decision 不变。final holdout 2019-03/06/09/12 继续封存。**

## 1. R4-D1 accepted result

```text
status                        COMPLETE
source status SHA256          522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
reviewed executable           51048259f8d9c61f324db07e05ded0a3c2f9d48e
runtime                       75.3963333 s
supported records             23876
fit_count                     0
R4 replay verified            true
holdout accessed              false
```

D1 结论：M3 确实以较弱的 instantaneous current continuity 换取更强的 session-state similarity，但该 aggregate geometry trade-off 不能完整解释 horizon/month outcome reversal。因此不能直接事后做“短期 Level、长期 M3”的硬切换。

## 2. R4-D2 冻结问题

R4-D2 仍是 zero-fit/read-only diagnostic，不是预测模型训练。

冻结主分数：

```text
S_current = (C_M3-C_Level)/(C_M3+C_Level+1e-12)
S_session = (QE_Level-QE_M3)/(QE_Level+QE_M3+1e-12)
B         = S_session-S_current
```

诊断 outcome：

```text
A = D_Level-D_M3
```

正 `A` 表示 M3 future divergence 更低。B 的 pooled quartile cutpoints 只由 issue-time geometry 产生，并固定复用于全部 horizon/month/20 cells；future target 不能参与 B、cutpoint 或 analog selection。

## 3. R4-D2 implementation identity

```text
D2 protocol merge             61f00f9293d012d599d4c2f8417fc9ea7a53a58e
D2 reviewed executable head   599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
D2 implementation merge       f5b0a2aa0576e40dcbe6b335dc206f0b7c2dce94
PR                             #86
CI                             PASS
launcher SHA256                a038412e716cab5fffbe8c1d557c955780b4085c943d3a2fe38d1ed4c45e481a
```

D2 实现会运行原冻结 D1，并被动抓取其同一批 23,876 supported records；随后先验证 accepted D1 aggregate digest，再计算冻结的 B/A 分层统计。D1 函数在抓取后恢复。该实现不新增 analog、不训练 gate/classifier/regressor/forecast model、不进行 metric learning/PCA/feature selection，也不允许 calendar month 进入 gating score。

## 4. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 run | **COMPLETE** |
| R4-D1 outcome | **ARCHIVED** |
| R4-D2 protocol | **FROZEN / MERGED** |
| R4-D2 implementation | **CI PASS / MERGED** |
| R4-D2 pinned launcher | **READY / locally audited** |
| R4-D2 local run | **NOT RUN YET** |
| Final holdout | **SEALED** |

下一步只允许：使用 pinned launcher 做 **exactly one development-only R4-D2 run**，随后上传最新 `evcf_r4_d2_status_*.json`。在 D2 结果归档前，不开始 adaptive Level/M3 forecasting model。
