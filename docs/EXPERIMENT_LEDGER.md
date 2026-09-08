# 实验与证据台账

更新：2026-09-08。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；已审HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`，main合并 `faa4cc8ad9051bd2f17f695e7c7741d769aee263`；修复实现 `6ded3bdd810a8115ea5b8a51091de71fab894a03`。数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，季节kW未授权。
- 开发集获取入口：PR #30 已合并；最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777`，main合并 `1d4c5f377f757aaea80b23987047f97899e958a4`。CI：1048 passed、2 skipped，compileall与Ruff PASS。
- 开发集raw获取/QA：用户本地v1.1启动器已完成01/04/07/10四个月获取；主控接受汇总交付。尚未创建processed快照、尚未训练新模型。
- Issue #22、#25、#26、#27均已完成关闭；当前方法开发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。
- Issue #25—#27的外置源码包、完整预测检查点和私有数组由用户本地保存；仓库登记协议、SHA、审查与去标识化结论，不冒称所有私有复现材料都已入库。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21已合并；Ridge/HGB、M1—M4 | `PASS_ACTIVE_SESSION_DROP_M4`；单月筛选 | PR #21 |
| 季节数据准备修订 | 获取1289/1509/1354个对象；8个缺失容器保留结构；PR #23已合并 | `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`；季节kW未授权 | PR #23 / review-5125619014 |
| 新增三月主实验 | 本地570次日级拟合；主控接受执行和汇总 | 8月通过月度规则，2/11月未满足全部条件；`MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 逐日与负值诊断 | 读取既有检查点，新增拟合0 | 负值不全是微小误差，但单纯置零不足以消除主要退化；非V2G测量证据 | Issue #25 |
| 三组会话特征删除 | 15项控制+570次消融；导出恢复不重训 | `EXPLORATORY_POSTHOC_NOT_CONFIRMATORY`；没有稳定支持统一删除整组 | Issue #26 |
| 预测组合 | 30项控制+300次校准拟合；测试预测复用 | 同为探索；简单平均留作强基线，校准加权未稳定超过简单平均 | Issue #27 |
| 月份目录盘点 | 3个登记worktree，只查目录，未训练/读数据内容 | 当时只发现已用四个月；新开发月份需另外获取 | DATA_USAGE_LEDGER |
| 开发集获取代码 | PR #30合并；固定01/04/07/10，holdout03/06/09/12阻断；完整CI通过 | 安全获取/QA入口 | PR #30 |
| 开发集raw获取/QA | v1.1启动器；01/04/07/10均完成官方API获取与月级QA | 四月均PASS；holdout未访问；未生成processed、未训练模型 | Issue #29 / evidence/development_acquisition_20260908.json |
| 可靠性门控方法开发 | 尚未执行新训练 | 当前研发方向；开发集/最终保留集已在下载前冻结 | Issue #29 |

执行次数、私有文件保全和逐点回放一致性依据本地工具记录；主控做代码/提交证据审查及可由上传汇总独立复算的统计，不冒称重跑用户私有模型。

## 3. 开发集raw获取结果

用户回传 `evcf_development_acquisition_status_20260907T182836Z.json`；原文件SHA256：

```text
7a11053b5a1d7230be595c5e7692349a381ca9b67ccf1418d58426aa86e8a1e9
```

冻结metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory quarantine=0、full-session quarantine=0、reason_codes均为空。`status=COMPLETE`、`holdout_accessed=false`、`models_trained=false`、`processed_data_created=false`。

v1.1报告4个metadata结构候选，其中1个通过冻结源验证；另外3个候选触发 `SOURCE_LAYOUT` 与 `SOURCE_MANIFEST` 并被拒绝。这是目录候选筛选诊断，不是四个开发月份失败。脱敏证据见 [development_acquisition_20260908.json](../evidence/development_acquisition_20260908.json)。

## 4. 季节主实验正式结果

| 月份 | 全月formal | 测试样本/计划 | 测试日 | M3相对M2 MAE改善：15/30/60/120/240 min |
| --- | ---: | ---: | ---: | --- |
| 2019-02 | 2388 | 1020/1041 | 11 | +2.4835% / +5.1766% / +4.3404% / +8.8822% / +6.0515% |
| 2019-08 | 2784 | 1281/1329 | 14 | +7.6912% / +9.7706% / +3.3306% / +1.9643% / -0.2329% |
| 2019-11 | 2517 | 1147/1233 | 13 | +17.3232% / -1.9796% / +1.9264% / -5.7261% / +6.4402% |

正值表示误差下降。跨月1/3通过，未达到预声明2/3；后续探索不重判原门控。2月早于5月，使用5月开发出的配置属于回溯方法实验，不是真实部署时序或分布外泛化验证。

## 5. 探索结果及不利证据

- 分组删除对完整M3：DROP_STATE 6/15改善、9/15退化；DROP_PROGRESS 5/15改善、10/15退化；DROP_REQUEST 10/15改善、5/15退化。没有统一删除整组的稳定依据。
- 简单平均相对M2的15个“月份×时距”MAE均改善，10个描述性区间全正；相对完整M3为10改善/5退化。11月15 min相对M3退化6.3404%；11月120 min相对M2虽MAE改善0.5834%，RMSE退化2.1556%。
- 校准加权相对简单平均为7改善/1相同/7退化；11月240 min所选w=0.4与0.5校准MAE只差约0.0054 A，留一日权重范围0.1—1.0，权重不稳定。
- 非负投影统一用于副本，不修改raw、真实标签、旧预测或门控；模型负输出不证明真实V2G。

这些后验结果说明M2与M3存在互补性，同时会话信息增量受时距和信息质量影响。它们用于提出Issue #29的可靠性门控假设，但不能作为新方法的独立验证。

## 6. 当前方法开发假设

候选方法采用标准Mixture-of-Experts/gating结构：M2为站级状态专家，完整M3为会话状态专家。门控只使用issue-time可得的低维可靠性变量和horizon，并在会话信息不足时向M2收缩/回退。

方法比较至少保留：M2、完整M3、0.5简单平均、可靠性门控。普通MoE/动态加权本身不是创新；2026年EV负荷研究已有动态堆叠和station/horizon-specific gating。当前可检验的新点是**会话可观测性驱动的可靠性门控与回退机制**。

若开发集上不能稳定超过简单平均，或必须依赖高复杂度不可解释调参，则停止该方向，不进入最终holdout。

## 7. 新数据分区与下一步

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；raw已获取并QA通过；
- 最终独立保留集：03、06、09、12；继续封存。

下一子步骤不是再次下载，而是为开发集构建清洗/15 min/M1–M3/泄漏审计/processed snapshot。详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 8. 冻结身份（SHA256）

参数源：PR #21 `model_selection_manifest.json`：`a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d`。

### Issue #25

```text
JPL_Seasonal_HGB_LocalRunner_20260907_v1_1.zip
11dca9e33592698395d502d8b898e68541f073e71996907ec239df3c4cbd7998
BUNDLE_SHA256SUMS.json
f14f6114e42e1801d54b4ae23c33e7d3b3208a87519c4d6a2d7be0847249e68d
protocol.json
65e0a3a51102683a1d1804f2e933e37bf5cad1702e9f070015d7cc6381ce611a
evcf_seasonal_summary_69868b80.zip
22186a354472d5c715ff646bcf0901e96f6a390cc55c06660737b0c3f917b0df
evcf_negative_diagnostic_381807b1.zip
40b195209f6d890a5d40c54cd560a20462dc19ff7dcc9775d0b3255030f8b1e9
```

### Issue #26

```text
JPL_Session_Group_Ablation_20260907_v1.zip
896d1206ad0abc37cb28db6b739d487e724b1f48bbeb160336de600c21d31973
BUNDLE_SHA256SUMS.json
9215b769027095c6075af37f1b875b6b9f019aa6e3690986ae6735e0f679625b
protocol.json
c4cf420a3fc8135adaaf394eb5cae74fd6b60dcab92e7138f3f9805d47fd3c73
evcf_ablation_export_recovery_f063a14e.zip
faeebc66fddabd2992dcd4634e55b0b50940d592984513b13eb7fdc28cb80c01
```

### Issue #27

```text
JPL_Forecast_Combination_20260907_v1.zip
71634e4f96735613649c4ae2447113f7480e4c61e1dcb7ba87ec8d0f02e70c91
BUNDLE_SHA256SUMS.json
636160eff1fdd51eab4a74068fd36ac194026e699a061a9e5bf87ea869fa9e00
protocol.json
87b615da9f01bbb0e52937aa92f7af919dc097f197c6930b2acfa9744b93e706
evcf_combination_summary_ad7ab376.zip
e967160302aec902c482ce29e020c999af645b94339cd397f7757366957d446b
```

## 9. 故障恢复与历史证据

v1季节启动源码检查缺陷由v1.1修复。消融 `PUBLIC_HASHES` 为Windows CRLF/LF清单兼容问题，恢复只规范新ZIP清单，保持载荷且新增拟合0。开发集获取首版启动器曾在联网前以 `VERIFIED_METADATA_NOT_LOCATED` 停止，原因是metadata目录定位规则过窄；v1.1按冻结结构与SHA识别后成功完成四个月获取。旧错误、原目录、未补写completed标记、恢复ZIP和M4负结果继续保留；不为仓库整洁重写历史证据。
