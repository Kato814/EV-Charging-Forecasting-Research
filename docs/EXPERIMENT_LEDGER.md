# 实验与证据台账

更新：2026-09-07。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账只记录已执行/已审查的事实，未重新训练模型；“接受交付”不等于科学假设通过或PR已经合并。

## 1. 版本与发布状态

最后已合并预测实验基线：PR #21，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。

季节代码/数据工作基线：PR #23 HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`；修复实现 `6ded3bdd810a8115ea5b8a51091de71fab894a03`。缺测技术阻断已在 [review-5125619014](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5125619014) 解除，数据准备条件通过，PR仍未合并。

Issue #25—#27的外置源码包及完整回传载荷通过对话交付/由用户本地保存，尚未作为本仓库源码commit或结果目录提交。这里保存结论、精确SHA与审查链接，不将其标成“全部复现材料已入库”。本轮文档维护没有改变生产源码、环境锁或冻结outputs。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21已合并；Ridge/HGB、M1—M4 | `PASS_ACTIVE_SESSION_DROP_M4`；单月筛选，不证明双源分解 | [PR #21](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/21) |
| 季节数据准备修订 | 获取1289/1509/1354个对象；8个缺失容器保留结构；修订已审 | `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`；季节kW未授权 | [PR #23条件验收](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5125619014) |
| 新增三月主实验 | 本地570次日级拟合；主控接受执行和汇总 | 8月通过月度规则，2/11月未满足全部条件；`MIXED_SEASONAL_EVIDENCE` | [Issue #25审查](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/25#issuecomment-5566541374) |
| 逐日与负值诊断 | 读取既有检查点，新增拟合0；汇总已审 | 负值不全是微小误差，但单纯置零不足以消除主要退化；非V2G测量证据 | [日级诊断](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/25#issuecomment-5567081161)、[幅度审查](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/25#issuecomment-5567368936) |
| 三组会话特征删除 | 15项控制+570次消融；导出恢复不重训 | `EXPLORATORY_POSTHOC_NOT_CONFIRMATORY`；没有稳定支持统一删除整组 | [Issue #26审查](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/26#issuecomment-5568854896) |
| 预测组合 | 30项控制+300次校准拟合；测试预测复用 | 同为探索；简单平均留作候选，校准加权未稳定超过简单平均 | [Issue #27审查](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/27#issuecomment-5570724142) |
| 月份目录盘点 | 3个登记worktree，只查目录，未训练/读数据内容 | 只发现已用四个月；没有已核实独立验证月份 | [数据用途台账](DATA_USAGE_LEDGER.md) |

执行次数、私有文件保全和逐点回放一致性依据本地工具记录；主控做的是代码/提交证据审查以及可由上传汇总独立复算的统计，不冒称重跑用户私有数据。旧CI测试数或历史测试结果不代表本轮新源码CI。

## 3. 季节主实验的正式结果（不被探索替换）

| 月份 | 全月formal | 测试样本/计划 | 测试日 | M3相对M2 MAE改善：15/30/60/120/240 min |
| --- | ---: | ---: | ---: | --- |
| 2019-02 | 2388 | 1020/1041 | 11 | +2.4835% / +5.1766% / +4.3404% / +8.8822% / +6.0515% |
| 2019-08 | 2784 | 1281/1329 | 14 | +7.6912% / +9.7706% / +3.3306% / +1.9643% / -0.2329% |
| 2019-11 | 2517 | 1147/1233 | 13 | +17.3232% / -1.9796% / +1.9264% / -5.7261% / +6.4402% |

正值为误差下降。跨月1/3通过，未满足预声明2/3；不因后续消融、投影或组合更好就重判原门控。5月参数用于早于5月的2月复核属于回溯方法实验，不是真实部署时序验证。各时距和样本之间有依赖，不把15个组合当15次独立试验。

## 4. 探索结果及不利证据

- 分组删除对完整M3：DROP_STATE为6/15个组合改善、9/15退化；DROP_PROGRESS为5/15改善、10/15退化；DROP_REQUEST为10/15改善、5/15退化。45项主比较没有区间完全位于“删除有益”正侧，不将跨零等同无效；固定全M3选参下的条件性证据，不是因果贡献或删减模型最优能力。
- 简单平均相对M2的15个组合MAE均改善，10个描述性区间全正；相对完整M3为10改善/5退化。11月15 min相对M3退化6.3404%；11月120 min相对M2虽MAE改善0.5834%，RMSE退化2.1556%。不宣称所有指标占优。
- 校准加权相对简单平均为7改善/1相同/7退化；原输出下没有稳定优势。11月240 min权重0.4与0.5的校准MAE只差约0.0054 A，留一日诊断权重范围0.1—1.0，不能将所选比例视为普适物理规律。
- 非负投影统一用于副本，不修改raw、真实标签、旧预测/旧门控；模型负输出不证明真实V2G。原清洗规则也不能用于循环证明raw绝无负值。

所有后验区间未作多重校正，只作描述。当前三个新增月份已参与探索，不能在其中挑最佳版本后称为新独立验证。简单平均只是下一独立验证候选，常规组合本身不是论文创新。

## 5. 冻结身份（SHA256）

参数源：PR #21的 `model_selection_manifest.json`，`a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d`。

### Issue #25

```text
运行包 JPL_Seasonal_HGB_LocalRunner_20260907_v1_1.zip
11dca9e33592698395d502d8b898e68541f073e71996907ec239df3c4cbd7998
BUNDLE_SHA256SUMS.json
f14f6114e42e1801d54b4ae23c33e7d3b3208a87519c4d6a2d7be0847249e68d
protocol.json
65e0a3a51102683a1d1804f2e933e37bf5cad1702e9f070015d7cc6381ce611a
结果 evcf_seasonal_summary_69868b80.zip
22186a354472d5c715ff646bcf0901e96f6a390cc55c06660737b0c3f917b0df
负值诊断 evcf_negative_diagnostic_381807b1.zip
40b195209f6d890a5d40c54cd560a20462dc19ff7dcc9775d0b3255030f8b1e9
```

### Issue #26

```text
运行包 JPL_Session_Group_Ablation_20260907_v1.zip
896d1206ad0abc37cb28db6b739d487e724b1f48bbeb160336de600c21d31973
BUNDLE_SHA256SUMS.json
9215b769027095c6075af37f1b875b6b9f019aa6e3690986ae6735e0f679625b
protocol.json
c4cf420a3fc8135adaaf394eb5cae74fd6b60dcab92e7138f3f9805d47fd3c73
回传恢复包 evcf_ablation_export_recovery_f063a14e.zip
faeebc66fddabd2992dcd4634e55b0b50940d592984513b13eb7fdc28cb80c01
```

### Issue #27

```text
运行包 JPL_Forecast_Combination_20260907_v1.zip
71634e4f96735613649c4ae2447113f7480e4c61e1dcb7ba87ec8d0f02e70c91
BUNDLE_SHA256SUMS.json
636160eff1fdd51eab4a74068fd36ac194026e699a061a9e5bf87ea869fa9e00
protocol.json
87b615da9f01bbb0e52937aa92f7af919dc097f197c6930b2acfa9744b93e706
结果 evcf_combination_summary_ad7ab376.zip
e967160302aec902c482ce29e020c999af645b94339cd397f7757366957d446b
```

本轮文档维护已对上述留存的3个源码ZIP、4个回传ZIP及3组BUNDLE/协议重新计算哈希，与登记值一致。没有重新解析私有数组或重算正式模型；原完整文件仍不在Git。

## 6. 故障恢复记录保全

v1季节启动源码检查缺陷由v1.1修复，见 [启动修复记录](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/25#issuecomment-5565997917)。消融 `PUBLIC_HASHES` 为Windows CRLF与LF清单比较缺陷，恢复只规范新ZIP校验清单、保持13件载荷，新增拟合0，见 [导出恢复记录](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/26#issuecomment-5568677673)。

旧错误、原目录、未补写的completed标记及恢复ZIP全部保留，不为维护台账改写。历史5月M4负结果及前后修正证据不删除。当前失效操作指令则从入口移除，不再以历史文件指挥新执行。
