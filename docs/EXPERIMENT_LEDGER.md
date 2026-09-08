# 实验与证据台账

更新：2026-09-08。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；已审HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`，main合并 `faa4cc8ad9051bd2f17f695e7c7741d769aee263`。数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，季节kW未授权。
- 开发集获取入口：PR #30 已合并；最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777`，main合并 `1d4c5f377f757aaea80b23987047f97899e958a4`。CI：1048 passed、2 skipped，compileall与Ruff PASS。
- 开发集raw获取/QA：用户本地v1.1启动器已完成01/04/07/10四个月获取；主控接受汇总交付。
- **开发集数据准备入口：PR #34已合并；最终HEAD `75590bf788712aaad3138367fe9e470b11777644`，main合并 `2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1`。最终CI：1058 passed、2 skipped，compileall与Ruff PASS。尚未执行用户本地processed准备或新模型训练。**
- Issue #22、#25、#26、#27均已完成关闭；当前方法开发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21已合并；Ridge/HGB、M1—M4 | `PASS_ACTIVE_SESSION_DROP_M4`；单月筛选 | PR #21 |
| 季节数据准备修订 | PR #23已合并 | `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`；季节kW未授权 | PR #23 |
| 新增三月主实验 | 本地570次日级拟合；主控接受执行和汇总 | 8月通过月度规则，2/11月未满足全部条件；`MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 逐日与负值诊断 | 读取既有检查点，新增拟合0 | 单纯置零不足以消除主要退化；非V2G测量证据 | Issue #25 |
| 三组会话特征删除 | 15项控制+570次消融；导出恢复不重训 | 不支持统一删除整组 | Issue #26 |
| 预测组合 | 30项控制+300次校准拟合；测试预测复用 | 简单平均为强基线；校准加权未稳定超过简单平均 | Issue #27 |
| 开发集获取代码 | 固定01/04/07/10，holdout阻断；完整CI通过 | 安全获取/QA入口 | PR #30 |
| 开发集raw获取/QA | 01/04/07/10官方API获取与月级QA | 四月均PASS；holdout未访问；未生成processed、未训练模型 | Issue #29 / evidence |
| **开发集processed准备代码** | **开发集专用协议+单月准备链复用；完整CI通过** | **只准备01/04/07/10；新异常fail-closed；不创建旧37件季节发布；holdout继续封存** | **PR #34** |
| 可靠性门控方法开发 | 尚未执行新训练 | 当前研发方向 | Issue #29 |

## 3. 开发集raw获取结果

用户回传 `evcf_development_acquisition_status_20260907T182836Z.json`；冻结metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory/full-session quarantine=0、reason_codes为空；`status=COMPLETE`、`holdout_accessed=false`、`models_trained=false`、`processed_data_created=false`。

## 4. PR #34开发集准备协议冻结

第一版实现曾准备复用旧02/08/11 seasonal YAML，因为数值预处理参数相同。主控在任何开发集processed结果产生前发现：旧YAML明确包含02/08/11月份身份、11月3596 s例外和37件发布合同，因此不能作为01/04/07/10协议。

最终PR #34新增 `acn_jpl_development_prep_2019.yaml`，在结果未知时预先固定：

- development months = 01/04/07/10；
- trajectory/full-session quarantine expected = 0/0；
- 清洗、15 min、coverage、24 h lookback、15/30/60/120/240 min horizon、M1–M3维度保持既有数值合同；
- local interim/processed only，`public_seasonal_release_created=false`；
- holdout 03/06/09/12 `access_allowed=false`；
- 旧02/08/11 YAML保持不变。

实现复用已审 `prepare_jpl_seasonal_month` 单月链，避免另写一套数据科学逻辑；专用上下文结束后月份allowlist、协议loader和quarantine builder全部恢复。

## 5. 季节主实验正式结果

| 月份 | 全月formal | 测试样本/计划 | 测试日 | M3相对M2 MAE改善：15/30/60/120/240 min |
| --- | ---: | ---: | ---: | --- |
| 2019-02 | 2388 | 1020/1041 | 11 | +2.4835% / +5.1766% / +4.3404% / +8.8822% / +6.0515% |
| 2019-08 | 2784 | 1281/1329 | 14 | +7.6912% / +9.7706% / +3.3306% / +1.9643% / -0.2329% |
| 2019-11 | 2517 | 1147/1233 | 13 | +17.3232% / -1.9796% / +1.9264% / -5.7261% / +6.4402% |

跨月1/3通过，原结论保持 `MIXED_SEASONAL_EVIDENCE`；后续探索不重判旧门控。

## 6. 探索结果及不利证据

- 分组删除：没有统一删除M3任一整组特征的稳定依据。
- 0.5简单平均相对M2的15个“月份×时距”MAE均改善，但相对M3非全面占优。
- 校准加权相对简单平均7改善/1相同/7退化，权重不稳定。
- 统一非负投影不改变“加权版尚无稳定优势”的判断；负预测不证明真实V2G。

## 7. 当前方法开发假设

候选方法采用标准Mixture-of-Experts/gating结构：M2为站级状态专家，完整M3为会话状态专家。门控只使用issue-time可得的低维可靠性变量和horizon，并在会话信息不足时向M2收缩/回退。

方法比较至少保留M2、完整M3、0.5简单平均、可靠性门控。若开发集上不能稳定超过简单平均，或必须依赖高复杂度不可解释调参，则停止该方向，不进入最终holdout。

## 8. 数据分区与下一步

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；raw已获取并QA通过；
- 最终独立保留集：03、06、09、12；继续封存。

**当前下一步是用户本地运行PR #34数据准备，之后主控审查processed快照、coverage/leakage、M1–M3样本及SHA；尚未授权可靠性门控训练。**

## 9. 历史冻结身份

Issue #25—#27的运行包、协议、结果SHA及故障恢复记录继续按原Issue和Git历史保存，不因当前阶段更新而重写。M4负结果同样保留。
