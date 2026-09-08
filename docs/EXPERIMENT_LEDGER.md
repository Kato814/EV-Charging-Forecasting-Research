# 实验与证据台账

更新：2026-09-08。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；已审HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`，main合并 `faa4cc8ad9051bd2f17f695e7c7741d769aee263`。数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，季节kW未授权。
- 开发集获取入口：PR #30 已合并；最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777`，main合并 `1d4c5f377f757aaea80b23987047f97899e958a4`。
- 开发集raw获取/QA：用户本地v1.1启动器已完成01/04/07/10四个月获取；四月均PASS。
- 开发集processed准备入口：PR #34已合并；最终HEAD `75590bf788712aaad3138367fe9e470b11777644`，main合并 `2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1`。
- **processed兼容性修复：PR #37已合并；最终HEAD `e47f05cb7a663df9c599270ac939c9301d26840b`，main合并 `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。CI：1058 passed、2 skipped，compileall与Ruff PASS。**
- Issue #22、#25、#26、#27均已完成关闭；当前方法开发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21已合并；Ridge/HGB、M1—M4 | `PASS_ACTIVE_SESSION_DROP_M4` | PR #21 |
| 季节数据准备修订 | PR #23已合并 | `CONDITIONAL_PASS`；季节kW未授权 | PR #23 |
| 新增三月主实验 | 本地570次日级拟合 | `MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 负值诊断、会话特征消融 | 读取既有检查点/570次消融 | 单纯置零不足；不支持统一删除整组 | Issue #25/#26 |
| 预测组合 | 30项控制+300次校准拟合 | 0.5简单平均留作强基线；校准加权未稳定超过简单平均 | Issue #27 |
| 开发集raw获取/QA | 01/04/07/10官方API获取与月级QA | 四月均PASS；holdout未访问；未训练模型 | Issue #29 |
| 开发集processed准备协议/代码 | 独立开发YAML+复用单月准备链 | 只准备01/04/07/10；holdout继续封存 | PR #34 |
| **processed首次实机失败** | **v1启动器；四月raw预检PASS；返回INCOMPLETE** | **不能解释为raw损坏；无模型训练、holdout未访问** | **Issue #29 / 用户状态JSON** |
| **processed只读诊断** | **no-write重放；2019-01定位到`validate_seasonal_cleaning_documents`** | **根因为旧`SEASONAL_MONTHS`兼容绑定遗漏；四月无partial输出** | **Issue #29 / 诊断JSON** |
| **processed兼容性修复** | **仅扩展/恢复`acn_jpl_gate1_prep.SEASONAL_MONTHS`并加回归测试** | **科学参数与数据规则不变** | **PR #37** |
| 可靠性门控方法开发 | 尚未执行新训练 | 当前研发方向 | Issue #29 |

## 3. 开发集raw获取结果

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

四个月trajectory/full-session quarantine=0、`holdout_accessed=false`。

## 4. processed协议、失败诊断与修复

PR #34在任何开发集processed结果产生前冻结独立 `acn_jpl_development_prep_2019.yaml`：开发月=01/04/07/10，trajectory/full-session quarantine期望均为0，数值清洗/15 min/coverage/lookback/horizon/M1–M3维度沿用已审合同，只写本地interim/processed，不创建旧37件季节发布，holdout03/06/09/12禁止访问。

首次Windows实机准备返回：

```text
status=INCOMPLETE
reason_code=DEVELOPMENT_PREPARATION_INCOMPLETE
preparation_reason_code=UNEXPECTED_ERROR
```

上传的只读诊断 `evcf_development_preparation_diagnostic_20260908T141021Z.json` 显示：

- `writes_suppressed=true`；
- 2019-01异常为 `ValueError`；
- 栈顶落在 `evcf.data.acn_jpl_gate1_prep.validate_seasonal_cleaning_documents()`；
- 对应失败行为是 `config.month not in SEASONAL_MONTHS`；
- 四个开发月在首次失败后均无interim/processed月份目录和processed manifest；
- holdout未访问，模型未训练。

PR #37因此只把 `evcf.data.acn_jpl_gate1_prep` 加入开发上下文的临时 `SEASONAL_MONTHS` 扩展/退出恢复集合，并增加回归断言。该修复不改变清洗公式、阈值、协议、特征、quarantine或模型。

## 5. 季节主实验正式结果

| 月份 | 全月formal | 测试样本/计划 | 测试日 | M3相对M2 MAE改善：15/30/60/120/240 min |
| --- | ---: | ---: | ---: | --- |
| 2019-02 | 2388 | 1020/1041 | 11 | +2.4835% / +5.1766% / +4.3404% / +8.8822% / +6.0515% |
| 2019-08 | 2784 | 1281/1329 | 14 | +7.6912% / +9.7706% / +3.3306% / +1.9643% / -0.2329% |
| 2019-11 | 2517 | 1147/1233 | 13 | +17.3232% / -1.9796% / +1.9264% / -5.7261% / +6.4402% |

跨月1/3通过，原结论保持 `MIXED_SEASONAL_EVIDENCE`；后续探索不重判旧门控。

## 6. 探索结果与当前假设

- 不支持统一删除M3任一整组特征；
- 0.5简单平均相对M2的15个“月份×时距”MAE均改善，但相对M3非全面占优；
- 校准加权未稳定超过简单平均；
- 统一非负投影不改变主要判断；负预测不证明真实V2G。

因此候选方法采用M2/M3双专家，门控只使用issue-time可得的低维可靠性变量和horizon，并在会话信息不足时向M2回退。若开发集上不能稳定超过0.5简单平均，停止该方向，不进入最终holdout。

## 7. 当前数据分区与下一步

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；
- 最终独立保留集：03、06、09、12。

**当前下一步是使用绑定PR #37合并提交的v1.1启动器重新执行开发集processed准备。成功并完成主控审查后，才授权可靠性门控训练。**

## 8. 历史证据

Issue #25—#27的运行包、协议、结果SHA、故障恢复和M4负结果继续按原Issue与Git历史保留，不因当前阶段更新而重写或删除。
