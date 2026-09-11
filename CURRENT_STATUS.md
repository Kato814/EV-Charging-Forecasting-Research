# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-11。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：开发集 2019-01/04/07/10、固定 M2/M3/0.5 强基线以及 S1 结构化双分支基线均已完成。S1 v1.3 在 PR #48 修复后首次完整跑通，正式判定为 `MIXED_STRUCTURED_SIGNAL`：整体 MAE 同时优于 M3 和 0.5 平均，5 个 horizon 中 4 个优于 0.5，但仅 2/4 个开发月优于 0.5，因此没有达到预先冻结的 PASS 稳定性要求。最终 holdout 2019-03/06/09/12 继续封存。当前唯一授权科研动作是对 MIXED 结果做只读失败分解，不立即上复杂模型。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | [#29 多时距会话贡献分解与结构化充电站负荷预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **S1 开发集 Go/No-Go 已完成；进入 MIXED 失败分解** |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| 最终 holdout | **2019-03 / 06 / 09 / 12，继续禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A；kW 未授权 |
| 强基线 | M2、M3、`0.5*M2+0.5*M3` |
| 当前结构化基线 | S1 = existing-session branch + future-arrival branch |
| S1 代码身份 | PR #48 reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82` |
| PR #48 merge | `0f85508f04e8192ec8c7949a512c488255fa58ef` |
| S1 v1.3 launcher | `evcf_structured_s1_launcher_v1_3.py` |
| launcher SHA256 | `dc43e61f3dbb55c93c8bf070a0fd61170555f309c7c15fe8ee889773979fa9b8` |
| v1.3 状态 | `COMPLETE` |
| v1.3 决策 | **`MIXED_STRUCTURED_SIGNAL`** |

## 2. 当前科学问题

当前候选主问题不是“可靠性门控”，也不是把 existing + arrival 双分支本身包装成创新。现阶段验证的是：

> 充电站负荷是否存在可复现的、随预测时距变化的“当前会话连续性 → 会话周转 / 未来到达主导”的机制转变；显式利用这一时距依赖结构，能否稳定优于强 M2/M3/0.5 基线。

G0 已表明 existing-session 对总负荷的 pooled 贡献从 15 min 的 97.38% 下降到 240 min 的 26.21%，future-arrival 补集由 2.62% 上升到 73.79%。该结构发现仍成立；S1 仅用于检验“目标分解是否具有预测价值”。

## 3. 冻结数据与身份

### Development processed snapshots

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

S1 v1.3 status 确认 development data unchanged，以上四个 snapshot SHA 与冻结值一致。

冻结 source expert protocol SHA256：

```text
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a
```

冻结 baseline private manifest SHA256：

```text
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd
```

S1 v1.3 运行中 baseline private cache unchanged；M2/M3 未重新训练。

## 4. 冻结基线与 S1 定义

- M2：24 h history/calendar + 当前站级 aggregate state。
- M3：M2 + 当前连接 session 的 legal fine-grained state pools。
- Equal：`0.5*M2 + 0.5*M3`。
- S1：`yhat_S1 = yhat_existing + yhat_arrival`。
- existing branch：M3 legal features + M3 已冻结 HGB 参数，目标为 issue time 已连接 sessions 的未来贡献。
- arrival branch：M2 legal features + M2 已冻结 HGB 参数，目标为未来到达 sessions 的贡献。

本轮禁止 branch-specific tuning、calibration、clipping、gate、HSMM/state-space、M2/M3 重调以及 final holdout 访问。

## 5. S1 v1.3 正式结果

### Overall pooled MAE

| 模型 | MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| **S1** | **28.594882** |

S1 相对 M3 改善 **2.0394%**，相对 Equal 改善 **1.1149%**。

### Pooled by horizon

| horizon | M3 | Equal | S1 | S1 vs Equal |
| ---: | ---: | ---: | ---: | ---: |
| 15 min | 8.540405 | 8.703288 | **8.317093** | **+4.44%** |
| 30 min | 15.916203 | 15.974630 | **15.894373** | **+0.50%** |
| 60 min | 26.552741 | **26.141292** | 27.181805 | **-3.98%** |
| 120 min | 40.920106 | 40.249069 | **39.991241** | **+0.64%** |
| 240 min | 54.021484 | 53.518152 | **51.589895** | **+3.60%** |

4/5 horizons 优于 Equal；最大 horizon 退化为 60 min 的 3.98%，仍低于冻结 5% 上限。

### Pooled by development month

| month | M3 | Equal | S1 | S1 vs Equal |
| --- | ---: | ---: | ---: | ---: |
| 2019-01 | 26.334178 | **25.957616** | 26.127334 | -0.65% |
| 2019-04 | 28.839079 | **28.725210** | 29.505123 | -2.72% |
| 2019-07 | 29.574292 | 29.968817 | **28.901955** | +3.56% |
| 2019-10 | 32.002202 | 31.022485 | **29.944196** | +3.48% |

仅 2/4 months 优于 Equal，因此没有满足 `PASS_STRUCTURED_SIGNAL` 所需的至少 3/4 months。

## 6. 冻结判定复核

`PASS_STRUCTURED_SIGNAL` 五项条件：

1. S1 pooled MAE < M3：**PASS**。
2. S1 pooled MAE < Equal：**PASS**。
3. 至少 3/5 horizons < Equal：**PASS，4/5**。
4. 至少 3/4 months < Equal：**FAIL，2/4**。
5. 任一 horizon 相对 Equal 退化 <= 5%：**PASS，最大 3.98%**。

因此正式判定保持：

```text
MIXED_STRUCTURED_SIGNAL
```

不得因整体结果接近 PASS 而修改冻结阈值。

## 7. MIXED 结果的初步失败分解

month × horizon 方向显示：

- 2019-04 是最明显的失败月：仅 15 min 优于 Equal，30/60/120/240 min 均退化，其中 60 min 退化约 10.69%。
- 2019-01 整体仅轻微退化，主要失败在 30/60 min。
- 2019-07 的主要收益来自 15/120/240 min，30/60 min 仍退化。
- 2019-10 整体最强，15/30/60/240 min 均改善，仅 120 min 退化。
- 跨月最不稳定的区域集中在 **30–120 min 的 turnover transition 区域，尤其 60 min**；240 min 的长期 arrival-dominant 方向相对更稳定。

这只用于定位失败来源，不等于新的方法结论。

## 8. 协议安全审计

S1 v1.3 status：

```text
status = COMPLETE
reason_code = null
holdout_accessed = false
m2_m3_retrained = false
gate_trained = false
hsmm_trained = false
state_space_model_trained = false
baseline_private_cache_unchanged = true
development_data_unchanged = true
fit_count = 550
```

status 未单列 `reconstruction_status` 字段；本轮以 `COMPLETE`、`reason_code=null` 且结构化公共结果完整产出作为“未报告 reconstruction/identity check 失败”的运行事实。不要把这一点扩写为额外科学结论。

## 9. 版本链与已知失败记录

- PR #41：M2/M3 OOS expert 基础实现。
- PR #43：JSON 标签键顺序修复。
- PR #45：Windows EOL 身份校验修复；accepted baseline expert code `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`。
- PR #47：S1 structured baseline；merge `7e914c1fe73376c720c376f0c12fa226a1082314`。
- S1 launcher v1：`MERGE_COMMIT_NOT_FOUND`，未训练。
- S1 launcher v1.1：`MERGE_COMMIT_NOT_FOUND_AFTER_EXPLICIT_FETCH`，未训练。
- S1 launcher v1.2：首次真实运行，`COMMON_ROW_IDENTITY_INVALID`；随后定位 baseline cache truth exact-equality 不一致。
- PR #48：cache truth tolerance 修复；reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`；merge `0f85508f04e8192ec8c7949a512c488255fa58ef`。
- S1 launcher v1.3：**COMPLETE / MIXED_STRUCTURED_SIGNAL**。

所有历史失败 status、worktree 和 private cache 保留，不自动清理。

## 10. 当前唯一下一步

严格按冻结 MIXED 规则，只做失败来源分析：

1. month × horizon；
2. existing branch 误差；
3. arrival branch 误差；
4. 判断长时距是否由 arrival branch 主导误差；
5. 判断短/中时距结构化分解是否破坏 M3 / Equal 优势。

当前**不授权**：final holdout、复杂深度模型、HSMM/state-space、可靠性 gate、branch-specific retuning、clipping/calibration 或重新选择开发月份。

## 11. 资产保护与维护

- S1 private output 与逐点预测继续仓库外本地保存，不提交 GitHub。
- 保留所有既有 worktree、raw/interim/processed、失败 status JSON 和外置实验目录。
- 禁止 `reset --hard`、`clean`、盲目 stash、force push。
- 重要运行、方法协议和科学结论变化继续同步维护 CURRENT_STATUS、HANDOFF、实验台账与 Issue #29。
