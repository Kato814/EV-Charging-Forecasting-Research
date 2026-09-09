# 实验与证据台账

更新：2026-09-09。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23已合并；数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，季节kW未授权。
- 开发集raw/processed：01/04/07/10均已完成；processed源状态SHA256 `4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153`。
- processed兼容性修复：PR #37已合并，main `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。
- M2/M3 OOS专家基础入口：PR #41已合并，main `653cb447382044911ce655175239f52f83dc892a`。
- JSON标签键顺序修复：PR #43已合并，main `7dda9d38a091f731c6f5c4ea74e293936996884c`。
- **Windows EOL实现身份校验修复：PR #45已合并，main `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`；最终CI 1071 passed、2 skipped，compileall/Ruff PASS。**
- 当前方法开发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月pilot | PR #21 | `PASS_ACTIVE_SESSION_DROP_M4` | PR #21 |
| 2/8/11季节主实验 | 570次日级拟合 | `MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 负值诊断/会话消融 | 诊断+570次消融 | 单纯置零不足；不支持统一删除整组 | Issue #25/#26 |
| 预测组合 | 30项控制+300次校准拟合 | 0.5简单平均为强基线；校准加权未稳定超过 | Issue #27 |
| 开发集raw/processed | 01/04/07/10 | 四月PASS；holdout未访问 | Issue #29 / evidence |
| 专家科学协议/基础入口 | 固定May HGB参数、日级OOS、共同测试行、私有缓存 | 科学协议冻结 | PR #41 |
| v1本地启动 | 模型拟合前STOPPED | JSON标签键顺序实现bug；无expert/gate/holdout | PR #43 / evidence |
| v1.1本地启动 | processed/environment preflight PASS后INCOMPLETE | Windows EOL导致 `IMPLEMENTATION_DRIFT` 误判；无模型持久化、无gate、无holdout | `evidence/development_expert_v1_1_preflight_failure_20260909.json` |
| **EOL-safe实现绑定** | **CRLF-only/真实修改/错误HEAD回归测试 + 全量CI** | **只修跨平台代码身份校验；科学协议不变** | **PR #45** |
| 可靠性门控 | 尚未执行 | 当前研发方向 | Issue #29 |

## 3. 开发集processed身份

```text
processed code = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
processed protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

总计11616/11808个valid90 bin，10872/11364个formal issue；raw unchanged，quarantine=0，holdout未访问。

## 4. 专家预测冻结协议

协议ID `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1`；May模型选择源manifest SHA256：

```text
a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d
```

M2/M3沿用May已选tier×horizon HGB参数；horizon=15/30/60/120/240 min；每月当地18日起OOS，每个当地午夜重训；训练行必须 `issue < cutoff` 且 `issue+h <= cutoff`；M2/M3共享测试行和truth；0.5简单平均同步计算；主预测无clipping/calibration；完整逐点预测仅本地私有缓存；本轮`gate_trained=false`。

## 5. 两次启动失败的技术结论

v1根因：canonical JSON使用 `sort_keys=True`，读取器错误依赖对象键顺序。PR #43改为集合校验+冻结顺序读取。

v1.1根因：原实现用 `git show` 的LF blob原始字节直接比较Windows working-tree字节，CRLF合法物化会被误判为漂移。PR #45改为精确HEAD、tracked regular-file存在、Git规范化`git diff --quiet`；CRLF-only通过，真实修改和错误HEAD继续fail closed。

两次失败均不产生可用于研究结论的专家结果；不修改processed，不访问最终holdout，不训练可靠性门控。

## 6. 已有科学结论

季节M3对M2仍为 `MIXED_SEASONAL_EVIDENCE`。会话特征整组删除无稳定统一收益；0.5简单平均是强基线；校准加权未稳定超过0.5。负预测不构成真实V2G证据。

## 7. 当前下一步

当前只授权 `evcf_dev_expert_launcher_v1_2.py`：SHA256 `42f4bee442b1586330344b15073079dab70fa093ee070c9131fcf5444e0d7abf`，绑定PR #45 main `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`。v1/v1.1均停用。成功后只回传脱敏状态JSON；20个逐点预测缓存和`private_manifest.json`留仓库外本地并必须保留。主控先审M2/M3/0.5开发基线，之后才设计可靠性门控训练。最终holdout 03/06/09/12继续封存。
