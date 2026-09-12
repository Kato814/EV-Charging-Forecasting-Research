# 代码与运行入口

更新：2026-09-12。**运行权限、当前 launcher 与固定代码身份只见 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。** 本文提供代码组织与保护规则，不再复制会过期的“当前唯一授权入口”。脚本存在或旧测试通过，不等于当前可以运行。

## 代码组织

`evcf.data` 提供 ACN 获取、QA、清洗、15 min 聚合和 issue-time 快照；`evcf.forecasting` 包含冻结的 M1—M4 编码、Ridge/HGB、开发集专家、S1/P1/R1 及相应诊断；`evcf.evaluation` 包含评价功能。使用哪一模块由本阶段协议决定，不能自动串行执行所有历史阶段。

已完成的专家基线、S1/P1/R1 结果及原代码身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)、[R1 outcome](../docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)。R1 已正式完成并为 MIXED；下一步只可能是获授权的失败来源分析，不是重新训练专家或 R1。

## 数据与因果边界

开发月固定 2019-01/04/07/10，原始/中间/处理数据和私有预测继续本地保存；最终 holdout 2019-03/06/09/12 禁止访问。已探索的 02/05/08/11 不得重新定义为独立 holdout。

原专家日级 OOS 规则为同月历史、当地午夜重拟合，训练须满足 `issue < cutoff` 且 `issue+h <= cutoff`。M2/M3 使用固定已选 HGB 参数和相同测试行。任何新实验不得静默改动这些冻结规则。

输入必须在 issue time 可得。未来真实组成、未来到达/离开、最终 kWh、测试误差或离线异常原因不得成为在线 predictor。预测缓存只能支持其已保存字段范围内的分析，不能虚称缓存含原始特征或模型系数。

## 本机执行契约

获授权的发布 launcher 放在仓库外，采用经 CI 审查的固定 commit；不切换用户已有工作树。必要时建立独立 detached code worktree；保留历史工作树、失败 JSON、日志和私有缓存。不要手工清理来绕过身份校验。

继续使用已验收环境，不自动升级依赖或更换 CUDA/显卡驱动。进度实时 flush/stream，最终 JSON 独立保存；必须报告实际设备、阶段、完成数及耗时。数组统计任务使用 CPU；批准的 GPU 模型可使用 RTX 5080，但不能为了使用 GPU 替换冻结学习器。PowerShell 命令保持单行。

若出现 INCOMPLETE，先审计最新状态，不盲目重复执行。上传默认仅包含指定 aggregate status，不上传逐行预测、模型、会话标识、凭据或绝对本地路径。

## 历史兼容修复与当前权限分离

PR #43 修复了 sorted-label JSON 的键顺序兼容；PR #45 修复了 Windows CRLF 下的实现身份误判。其代码、测试和失败记录仍保留。旧专家 v1/v1.1/v1.2 launcher 不再因本文而获得执行授权，也不能替代当前诊断入口。

禁止因旧代码索引、旧路线图或旧开源候选清单重新启动门控、P1 rescue、Deep Sets、Set Transformer、MoE 或任何 holdout 计算。最新明确授权和 CURRENT_STATUS 优先。
