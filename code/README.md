# 代码与运行入口

更新：2026-09-09。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并基础实现

`evcf.data`包含ACN获取、QA、清洗、15 min及issue-time快照；`evcf.forecasting`包含M1—M4历史编码、Ridge/HGB、开发集M2/M3 OOS专家控制器；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测基线；PR #23季节数据准备；PR #30开发集raw；PR #34开发集processed；PR #37修复开发月清洗校验兼容；PR #41新增固定M2/M3专家OOS基础入口；PR #43修复canonical sorted-label JSON；**PR #45修复Windows CRLF下实现身份误判。**

## 开发集processed资产

01/04/07/10 raw和processed均已PASS；四个snapshot SHA已在CURRENT_STATUS与DATA_USAGE_LEDGER冻结。processed不重复构建、不提交Git。

## 专家预测冻结协议

M2/M3沿用5月已选HGB参数，开发月不重新调专家超参数；15/30/60/120/240 min；每月当地18日起测试、当地午夜日级重训；训练只用 `issue < cutoff` 且 `issue+h <= cutoff` 的同月formal行；M2编码204、M3编码391；raw NaN+固定missing indicators；无imputation/scaling/clipping/calibration；M2/M3共享test rows/truth，0.5简单平均同步计算；gate不在本轮训练；逐点预测只保存在仓库外本地目录。

## 本地兼容修复链

### PR #43
processed的 `labels.jsonl.gz` 采用 `sort_keys=True`，旧读取器错误依赖JSON键顺序。兼容层改为验证精确horizon键集合，并始终按15/30/60/120/240读取值。v1故障关闭。

### PR #45
v1.1通过processed/environment预检后以 `IMPLEMENTATION_DRIFT` 停止。根因是旧实现将 `git show` LF blob字节与Windows working-tree CRLF字节直接比较。PR #45改为：
- checkout `HEAD` 必须精确等于冻结提交；
- 绑定文件必须为受Git跟踪的普通文件；
- 使用Git规范化 `git diff --quiet --no-ext-diff <commit> -- <paths>` 判断真实内容漂移；
- CRLF-only物化允许通过；真实内容修改和错误HEAD仍fail closed。

PR #45 main：`e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`；CI 1071 passed、2 skipped，compileall/Ruff PASS。

## 当前唯一授权入口

仅使用外置：

```text
evcf_dev_expert_launcher_v1_2.py
SHA256 42f4bee442b1586330344b15073079dab70fa093ee070c9131fcf5444e0d7abf
```

v1.2绑定PR #45 main，创建新的 `code-v3` detached worktree，并将新私有预测写入仓库外新的 `...jpl-development-expert-runs-v2` 目录。**v1和v1.1均停用，不得再次执行。** 旧 `run_jpl_gate1_pilot.py` 是5月历史入口，不能替代开发集CLI。

## 未授权模块

可靠性门控训练要等专家基线审查后再开始。最终holdout 03/06/09/12、M4恢复、Gate2、概率预测、调度、联邦和GPU深度扩展均未授权。

## 环境与保护

本地继续使用 `evcf-gate1-pilot` / Python3.11.16。raw/interim/processed、完整预测、模型和私有路径不提交。所有既有worktree、v1/v1.1失败状态JSON与外置运行目录继续保留，不做自动清理。
