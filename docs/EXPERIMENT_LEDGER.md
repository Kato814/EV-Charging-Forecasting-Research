# 实验与证据台账

更新：2026-09-09。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，季节kW未授权。
- 开发集raw获取入口：PR #30 已合并；01/04/07/10 raw获取均PASS。
- 开发集processed准备入口：PR #34已合并；独立开发集YAML与固定四月准备链。
- processed兼容性修复：PR #37已合并；main `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`；CI 1058 passed、2 skipped，compileall/Ruff PASS。
- **开发集processed本地准备：v1.1已完成，01/04/07/10四个月全部PASS。源状态SHA256 `4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153`。**
- 当前方法开发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21 | `PASS_ACTIVE_SESSION_DROP_M4` | PR #21 |
| 2/8/11季节主实验 | 本地570次日级拟合 | `MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 负值诊断/会话消融 | 诊断+570次消融 | 单纯置零不足；不支持统一删除整组 | Issue #25/#26 |
| 预测组合 | 30项控制+300次校准拟合 | 0.5简单平均为强基线；校准加权未稳定超过 | Issue #27 |
| 开发集raw获取/QA | 01/04/07/10 | 四月均PASS；holdout未访问 | Issue #29 |
| processed协议/代码 | PR #34 | 只准备开发月；holdout封存 | PR #34 |
| processed兼容性修复 | PR #37 | 仅修旧月份白名单兼容，不改科学参数 | PR #37 |
| **开发集processed准备** | **v1.1完整运行** | **四月PASS；raw unchanged；未训练模型；holdout未访问** | **Issue #29 / evidence/development_preparation_20260909.json** |
| 可靠性门控方法开发 | 尚未执行新训练 | 当前研发方向 | Issue #29 |

## 3. 开发集processed结果

```text
code commit = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | sessions | valid90 / bins | formal / scheduled | processed snapshot SHA256 | 状态 |
| --- | ---: | ---: | ---: | --- | --- |
| 2019-01 | 1372 | 2970 / 2976 | 2836 / 2865 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 1524 | 2772 / 2880 | 2552 / 2769 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 1489 | 2931 / 2976 | 2742 / 2865 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 1673 | 2943 / 2976 | 2742 / 2865 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

总计：11616/11808个15 min格达到valid90；10872/11364个scheduled issue进入formal集合。四月 `raw_unchanged=true`，trajectory/full-session quarantine=0，`holdout_accessed=false`，`models_trained=false`。

`invalid_skipped_session_count=0` 只表示结构保留合同下没有跳过会话，不能单独解释为“无无效容器”。

四月power audit为 `KW_RECONSTRUCTION_CANDIDATE`，但不改变当前A口径预测授权。

## 4. 故障/恢复记录

首次v1准备失败于 `acn_jpl_gate1_prep` 旧 `SEASONAL_MONTHS` 白名单；只读诊断确认没有partial开发月输出。PR #37修复后v1.1完整PASS。旧失败JSON和诊断JSON继续保留，不删除或改写。

## 5. 季节主实验正式结果

| 月份 | 全月formal | 测试样本/计划 | 测试日 | M3相对M2 MAE改善：15/30/60/120/240 min |
| --- | ---: | ---: | ---: | --- |
| 2019-02 | 2388 | 1020/1041 | 11 | +2.4835% / +5.1766% / +4.3404% / +8.8822% / +6.0515% |
| 2019-08 | 2784 | 1281/1329 | 14 | +7.6912% / +9.7706% / +3.3306% / +1.9643% / -0.2329% |
| 2019-11 | 2517 | 1147/1233 | 13 | +17.3232% / -1.9796% / +1.9264% / -5.7261% / +6.4402% |

跨月1/3通过，原结论保持 `MIXED_SEASONAL_EVIDENCE`。

## 6. 当前方法假设与下一步

候选方法采用M2/M3双专家。门控只使用issue-time可得低维可靠性变量和horizon，并在会话信息不足时向M2回退。开发阶段至少保留M2、完整M3、0.5简单平均、可靠性门控。

下一步先冻结开发集专家预测协议和内部开发切分，再生成可复用M2/M3预测；尚未授权最终holdout或新模型本地运行。若门控不能稳定超过简单平均，则停止该方向。
