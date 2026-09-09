# 代码与运行入口

更新：2026-09-09。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并基础实现

`evcf.data`包含ACN获取、QA、清洗、15 min及issue-time快照；`evcf.forecasting`包含M1—M4历史编码、Ridge/HGB、开发集M2/M3 OOS专家控制器；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测基线；PR #23季节数据准备；PR #30开发集raw；PR #34开发集processed；PR #37修复开发月清洗校验兼容；PR #41新增开发集固定M2/M3专家OOS基础入口；**PR #43修复真实processed标签JSON键顺序兼容并新增v1.1 CLI。**

## 开发集processed资产

01/04/07/10 raw和processed均已PASS；四个snapshot SHA已在CURRENT_STATUS与DATA_USAGE_LEDGER冻结。processed不重复构建、不提交Git。

## 专家预测冻结协议

PR #41 main合并 `653cb447382044911ce655175239f52f83dc892a`。冻结规则：
- M2/M3沿用5月已选HGB参数，开发月不重新调专家超参数；
- 15/30/60/120/240 min；每月当地18日起测试；每天当地午夜重训；
- 训练只用当时已到达标签：`issue < cutoff` 且 `issue+h <= cutoff`；
- M2编码204、M3编码391；raw NaN+固定missing indicators；
- 无imputation/scaling/clipping/calibration；
- M2/M3相同test rows/truth；0.5简单平均同步计算；
- gate不在本轮训练；
- 逐点预测缓存只保存在仓库外部本地目录，GitHub不接收。

## v1预检故障与v1.1入口

首次外置 `evcf_dev_expert_launcher_v1.py` 在任何模型拟合前以 `DEVELOPMENT_PROCESSED_NOT_VERIFIED` 停止。根因不是数据损坏：processed写入 `labels.jsonl.gz` 时使用 `sort_keys=True`，而PR #41读取器错误要求JSON对象horizon键保持另一插入顺序。

PR #43 main合并：

```text
7dda9d38a091f731c6f5c4ea74e293936996884c
```

最终CI：1068 passed、2 skipped，compileall/Ruff PASS。

新增：
- `evcf.forecasting.acn_jpl_development_experts_compat`：只修正标签JSON对象键顺序语义，验证精确horizon键集合并按冻结顺序读取；
- `scripts/run_jpl_development_experts_v1_1.py`：v1.1官方本地CLI；
- 真实 `sort_keys=True` 序列化回归测试；
- 预检失败证据记录。

**当前唯一授权通过外置v1.1启动器执行一次开发集专家预测。旧v1启动器已停用，不得再次执行。** 旧 `run_jpl_gate1_pilot.py` 仍是5月历史入口，不能替代开发集CLI。

## 未授权模块

可靠性门控训练要等专家基线审查后再开始。最终holdout 03/06/09/12、M4恢复、Gate2、概率预测、调度、联邦和GPU深度扩展均未授权。

## 环境与保护

本地继续使用 `evcf-gate1-pilot` / Python3.11.16。raw/interim/processed、完整预测、模型和私有路径不提交。所有既有worktree、首次v1失败状态JSON与失败/诊断资料继续保留；v1.1使用新的代码worktree，不要求删除旧v1 worktree。
