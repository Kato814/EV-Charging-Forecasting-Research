# 代码与运行入口

更新：2026-09-08。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并的基础实现

`evcf.data`包含ACN获取、QA、5月清洗、语义审计、15 min及issue-time快照；`evcf.forecasting`包含M1—M4历史编码、Ridge/HGB及滚动pilot；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测实验基线；PR #23季节数据准备已合并。旧季节数据准备仍为 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`。

## 开发集获取与准备入口

### PR #30：raw获取

- `evcf.data.acn_jpl_development_months`：专用上下文内批准01/04/07/10；
- `scripts/acquire_jpl_development.py`：固定开发集获取/QA；
- 03/06/09/12不批准，无任意月份覆盖参数；
- 新开发月不继承11月3596 s轨迹隔离特例。

开发集raw已在用户本地完成并四月QA PASS，不应再次运行获取命令。

### PR #34：interim/processed准备

PR #34最终HEAD：`75590bf788712aaad3138367fe9e470b11777644`；main合并：`2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1`。

新增：
- `code/configs/acn_jpl_development_prep_2019.yaml`：01/04/07/10专用冻结协议；
- `evcf.data.acn_jpl_development_prep`：固定四月控制器，复用已审 `prepare_jpl_seasonal_month`；
- `scripts/prepare_jpl_development.py`：显式授权的本地数据准备CLI。

协议规定四个开发月trajectory/full-session quarantine均为0；只生成本地ignored interim/processed、15 min、M1–M3 snapshot/feature blocks和SHA，不创建旧02/08/11的37件季节发布。最终holdout继续阻断。

### PR #37：清洗校验兼容性修复

首次Windows processed准备经只读诊断定位：`evcf.data.acn_jpl_gate1_prep.validate_seasonal_cleaning_documents()` 仍使用按值导入的旧02/08/11 `SEASONAL_MONTHS`，而PR #34开发上下文未扩展该模块，因此2019-01在清洗文档校验时被拒绝。

PR #37最终HEAD：`e47f05cb7a663df9c599270ac939c9301d26840b`；main合并：`c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。最终CI：1058 passed、2 skipped，compileall/Ruff PASS。

修复只把 `acn_jpl_gate1_prep` 加入临时月份兼容列表并在上下文退出时恢复；没有改清洗参数、协议、特征、quarantine、模型或holdout权限。

## 当前本地执行入口

当前只允许使用外置 `evcf_dev_preparation_launcher_v1_1.py` 重试01/04/07/10 processed准备：

- 精确绑定PR #37 main合并提交；
- 使用新的detached code worktree，不删除旧PR #34代码worktree；
- 重试前再次校验metadata/raw，并要求四个月当前不存在interim/processed月份目录；
- 不联网、不训练模型、不访问03/06/09/12；
- 成功后只回传脱敏status JSON。

## 已执行的外置运行包

| 工作 | 外置目录 | 状态 |
| --- | --- | --- |
| Issue #25季节复核 | `evcf_seasonal_runner_v1_1` | 已执行并审查，`MIXED_SEASONAL_EVIDENCE` |
| Issue #26分组消融 | `evcf_session_ablation_v1` | 已执行；导出恢复完成 |
| Issue #27预测组合 | `evcf_forecast_combination_v1` | 已执行；简单平均留作强基线 |

这些目录及 `local_runs/private`、绑定、错误/恢复ZIP继续保留。

## 当前模型开发与未授权模块

当前Issue #29开发M2/M3双专家的**会话信息可靠性门控与向M2回退**。普通MoE/动态加权不是创新点。开发阶段至少比较M2、完整M3、0.5简单平均和可靠性门控。

**当前尚未授权新门控训练。**必须先完成并审查01/04/07/10 processed数据准备。

最终holdout 03/06/09/12、Gate2、概率、调度、联邦和GPU深度扩展均未授权。

## 环境与保护

本地继续使用 `evcf-gate1-pilot` / Python3.11.16，不无条件升级。开发集processed准备为本地CPU数据处理，不需要ACN token、不下载新raw、不训练模型。

raw/interim/processed、完整预测、模型和私有路径不提交。用户原main未提交修改和已有worktree不清理；旧PR #34 code worktree和新v2 code worktree均保留。
