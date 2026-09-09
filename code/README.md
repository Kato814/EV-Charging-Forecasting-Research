# 代码与运行入口

更新：2026-09-09。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并基础实现

`evcf.data`包含ACN获取、QA、清洗、15 min及issue-time快照；`evcf.forecasting`包含M1—M4历史编码、Ridge/HGB、开发集M2/M3 OOS专家控制器；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测基线；PR #23季节数据准备；PR #30开发集raw；PR #34开发集processed；PR #37修复开发月清洗校验兼容；**PR #41新增开发集固定M2/M3专家OOS入口。**

## 开发集processed资产

01/04/07/10 raw和processed均已PASS；四个snapshot SHA已在CURRENT_STATUS与DATA_USAGE_LEDGER冻结。processed不重复构建、不提交Git。

## PR #41专家预测入口

PR #41最终HEAD `ac4e4b2b75aa46429256b6a535e1e88a8a7a61f8`；main合并 `653cb447382044911ce655175239f52f83dc892a`；CI 1066 passed、2 skipped，compileall/Ruff PASS。

新增：
- `code/configs/acn_jpl_development_experts_2019.yaml`：开发集专家OOS冻结协议；
- `evcf.forecasting.acn_jpl_development_experts`：snapshot验证、May参数绑定、日级滚动HGB、聚合指标和私有预测缓存；
- `scripts/run_jpl_development_experts.py`：显式授权、安全输出的开发集专家CLI。

固定规则：
- M2/M3沿用5月已选HGB参数，开发月不重新调专家超参数；
- 15/30/60/120/240 min；每月当地18日起测试；每天当地午夜重训；
- 训练只用当时已到达标签：`issue < cutoff` 且 `issue+h <= cutoff`；
- M2编码204、M3编码391；raw NaN+固定missing indicators；
- 无imputation/scaling/clipping/calibration；
- M2/M3相同test rows/truth；0.5简单平均同步计算；
- gate不在本轮训练；
- 逐点预测缓存只保存在仓库外部本地目录，GitHub不接收。

**当前已授权通过外置安全启动器执行一次开发集专家预测。**旧 `run_jpl_gate1_pilot.py` 仍是5月历史入口，不能替代新CLI。

## 未授权模块

可靠性门控训练要等专家基线审查后再开始。最终holdout 03/06/09/12、M4恢复、Gate2、概率预测、调度、联邦和GPU深度扩展均未授权。

## 环境与保护

本地继续使用 `evcf-gate1-pilot` / Python3.11.16；scikit-learn安装会提供冻结环境中的threadpoolctl 3.6.0，原Gate1依赖合同不修改。raw/interim/processed、完整预测、模型和私有路径不提交。所有既有worktree与失败/诊断资料继续保留。
