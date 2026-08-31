# 计算与实验执行策略

## 1. 冻结决策

本项目采用“**GitHub 作为代码与审计控制面，本地工作站作为数据与计算执行面**”的混合架构。

```text
GitHub / GitHub Actions
  ├─ 代码、配置、文档、Issue、PR和版本审计
  ├─ 代码规范、单元测试、CPU小样本冒烟测试
  └─ 不保存Token、原始会话轨迹、完整模型权重和大型实验结果

本地Windows工作站（RTX 5080 16 GB）
  ├─ ACN官方API下载与原始数据管理
  ├─ 全量清洗、15 min聚合、滚动样本构造
  ├─ 传统机器学习与深度学习训练
  ├─ 超参数搜索、多随机种子、消融和概率场景生成
  └─ 后续滚动优化与预测—调度闭环实验
```

大型训练任务不使用标准 GitHub-hosted runner。当前不购买 GitHub GPU larger runner，也不立即把个人工作站注册为 self-hosted runner。

## 2. 任务—环境分配

| 任务 | 默认执行位置 | 原因 |
|---|---|---|
| Ruff、编译检查、仓库清单校验 | GitHub Actions | 快速、无数据依赖、适合PR门禁 |
| 单元测试 | GitHub Actions + 本地 | CI保证代码可合并，本地用于开发反馈 |
| 合成小数据CPU冒烟测试 | GitHub Actions | 检查接口和端到端流程，不追求性能 |
| ACN Token调用与原始数据下载 | 本地 | Token和原始用户级数据不得进入GitHub |
| 大型数据解压、清洗、聚合 | 本地CPU/内存 | 需要本地raw目录和较大磁盘空间 |
| LightGBM、统计模型、小型基线 | 本地CPU | 便于使用完整数据并保存可恢复中间结果 |
| LSTM、TCN、Transformer、概率生成模型 | 本地RTX 5080 | 充分利用16 GB显存，避免云端GPU费用与数据传输 |
| 多随机种子、消融、超参数搜索 | 本地RTX 5080，串行或受控并行 | 单GPU下统一调度，防止显存争抢 |
| 随机/鲁棒MPC、调度求解 | 本地CPU；需要神经网络梯度时使用本地GPU | 优化器和数据均在本地闭环 |
| 正式结果复核 | 本地重跑 + GitHub提交摘要 | Git保存配置、哈希和聚合结果，不保存raw |

## 3. GitHub Actions职责边界

标准CI必须满足：

- 使用 GitHub-hosted CPU runner；
- 不访问 `ACN_API_TOKEN`；
- 不读取 `data/raw`、`data/interim`、本地模型目录；
- 单个工作流目标时长不超过15分钟；
- 只运行确定性或固定种子的轻量测试；
- `GITHUB_TOKEN`默认只授予 `contents: read`；
- PR触发的工作流不得调用本地GPU或任何self-hosted runner。

CI允许的测试数据：

- 代码内最小合成样本；
- 去标识化、小体量、许可允许提交的fixture；
- 聚合统计和预期输出摘要。

CI禁止：

- 正式训练；
- 大规模超参数搜索；
- 下载ACN全量时间序列；
- 上传原始会话轨迹；
- 以GitHub artifact长期保存大模型。

## 4. 本地RTX 5080执行规范

### 4.1 推荐软件基线

- Windows 11 64-bit；
- Python 3.11；
- 独立Conda环境，不使用base环境直接训练；
- PyTorch稳定版，CUDA构建版本不低于12.8；
- 固定依赖锁文件和环境报告；
- 所有正式实验记录GPU名称、显存、PyTorch、CUDA runtime、驱动和Python版本。

RTX 5080属于Blackwell架构。环境必须通过：

```bash
python scripts/check_compute_environment.py --require-cuda --min-vram-gb 14
```

在环境核验通过前，不启动正式GPU实验。

### 4.2 单GPU调度原则

- 默认一次只运行一个大型训练任务；
- 超参数搜索先做小预算筛选，再对少量候选完整训练；
- 多随机种子顺序执行，不在同一GPU上盲目并发；
- 使用混合精度前必须做数值一致性核验；
- 每次运行保存可恢复checkpoint，但checkpoint不提交Git；
- 长任务必须支持断点续跑和安全停止；
- 记录峰值显存和每epoch耗时。

### 4.3 建议显存预算

RTX 5080标称16 GB显存。正式脚本应预留至少1.5—2 GB系统/框架余量，默认控制训练峰值在约14 GB以内。出现OOM时按以下顺序处理：

1. 降低batch size；
2. 启用梯度累积；
3. 缩短输入窗口或减少场景并行数；
4. 使用混合精度；
5. 减小模型宽度；
6. 最后才考虑更换硬件或云GPU。

## 5. 实验产物分层

### 5.1 仅保存在本地

```text
data/raw/
data/interim/
data/processed/
models/
checkpoints/
outputs/runs/<run_id>/predictions/
outputs/runs/<run_id>/large_arrays/
```

包括：

- 原始会话记录；
- 用户级时间序列；
- 访问凭据；
- 大型Parquet/NPZ/HDF5文件；
- 完整模型权重；
- 大规模预测场景。

### 5.2 可以提交GitHub

- 代码和测试；
- YAML/JSON实验配置；
- 环境报告（不得含用户名、路径和Token）；
- 输入数据版本与SHA-256清单；
- 聚合指标；
- 小型图表；
- 统计检验结果；
- 运行清单和失败原因；
- 不含用户标识的QA摘要。

### 5.3 正式实验最小记录

每次正式运行至少保存：

```text
run_id
commit_sha
config_sha256
data_snapshot_id
data_manifest_sha256
random_seed
split_definition
python_version
torch_version
cuda_runtime
gpu_name
gpu_vram
start_time_utc
end_time_utc
exit_status
metrics
```

## 6. Self-hosted runner策略

当前状态：**DEFERRED（暂缓）**。

不立即将个人电脑注册为GitHub self-hosted runner，原因包括：

- self-hosted任务不天然处于一次性干净环境；
- 工作流代码可以访问本机文件和进程；
- PR触发机制若配置不当会带来安全风险；
- 当前仍处于Gate 0—Gate 1，直接本地命令更简单可控。

仅在以下条件全部满足后再评估：

1. 训练入口、配置和恢复机制稳定；
2. 需要无人值守夜间队列；
3. 仓库保持private；
4. runner使用独立低权限Windows账户；
5. 只允许 `workflow_dispatch` 手动触发；
6. 禁止 `pull_request` 触发GPU任务；
7. workflow权限固定为只读；
8. raw数据和Token不作为GitHub secret注入，而由本机受控环境提供；
9. runner标签至少包含 `self-hosted`, `windows`, `x64`, `rtx5080`, `research-local`；
10. 每次执行前后清理工作目录并保存审计日志。

即使启用self-hosted runner，计算仍发生在本地RTX 5080上；GitHub只负责排队和记录，不提供计算资源。

## 7. 当前阶段执行安排

### Gate 0与完整月数据准备

- GitHub：维护下载器、QA代码、测试和PR；
- 本地：使用Token下载JPL 2019-05完整 `/ts`；
- 本地：运行清洗与站级15 min聚合；
- GitHub：提交去标识化QA与聚合摘要。

### Gate 1

- GitHub Actions：只运行M1—M4接口和小合成样本测试；
- 本地CPU/GPU：运行完整JPL月份的M1—M4基线；
- 首轮模型应优先使用统计/机器学习和小型神经网络，不直接进行大规模架构搜索。

### Gate 2及以后

- 正式深度概率模型、多种子和消融全部在本地RTX 5080运行；
- GitHub保留可复现配置、结果摘要和审查历史；
- 只有在本地算力成为明确瓶颈后，才评估额外云GPU。

## 8. 最终原则

```text
GitHub Actions = 质量门禁，不是训练集群
本地RTX 5080 = 正式数据处理、训练和优化的主执行平台
GitHub仓库 = 唯一代码与证据索引，不是原始数据仓库
```
