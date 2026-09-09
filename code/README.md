# 代码与运行入口

更新：2026-09-09。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并基础实现

`evcf.data`包含ACN获取、QA、清洗、15 min及issue-time快照；`evcf.forecasting`包含M1—M4历史编码、Ridge/HGB及滚动pilot；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测基线；PR #23季节数据准备已合并；PR #30提供开发集raw入口；PR #34提供开发集processed入口；PR #37修复开发月清洗校验兼容性。

## 开发集数据资产

01/04/07/10 raw和processed均已在用户本地完成，四个月PASS。processed固定使用PR #37 main合并 `c1ff4e675ae14e7667e0c6b7f887fb15319aff38` 与开发集协议SHA `4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1`。

本地processed目录包含：
- `station_15min.jsonl.gz`；
- `m1.jsonl.gz`、`m2.jsonl.gz`、`m3.jsonl.gz`、`labels.jsonl.gz`；
- M1/M2/M3的 `values.npy`、`issue_times.npy`、`nullable_mask.npy`；
- `data_snapshot_manifest.json`；
- interim中的 `cleaned_sessions.jsonl.gz` 及manifest。

这些均为本地ignored资产，不提交Git，不重复构建。

## 当前模型开发入口状态

当前Issue #29进入M2/M3专家预测与可靠性门控开发。**尚不存在已授权的开发集专家预测CLI；旧 `scripts/run_jpl_gate1_pilot.py` 是5月固定入口，不能通过改月份直接复用。**

下一代码动作是新增开发集专用专家预测控制器/CLI：
- 读取并核验四个月processed manifest和冻结snapshot SHA；
- 使用M2/M3标准编码维度（M2 204、M3 391）；
- 使用5月已选HGB专家参数，不在开发月重新搜索专家超参数；
- 按冻结时间协议产生out-of-sample滚动预测并私有缓存；
- 同一月份/时距的M2/M3使用共同测试行；
- 不裁剪、不校准主预测；统一非负投影只作后续敏感性；
- 输出GitHub只允许脱敏聚合证据，完整预测缓存留本地。

专家预测基线审查通过后，才实现低维可靠性门控。

## 未授权模块

当前不恢复M4，不启动Gate2、概率预测、调度、联邦或GPU深度扩展。最终holdout 03/06/09/12在方法冻结前继续禁止访问。

## 环境与保护

本地继续使用 `evcf-gate1-pilot` / Python3.11.16。raw/interim/processed、完整预测、模型和私有路径不提交。原main未提交修改、所有worktree、失败/诊断JSON和外置实验目录继续保留。
