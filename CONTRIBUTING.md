# Contributing

先读 [CURRENT_STATUS.md](CURRENT_STATUS.md)、[AGENTS.md](AGENTS.md) 与当前Issue最新主控意见。工作流见 [docs/WORKFLOW.md](docs/WORKFLOW.md)。

## 文献新增

先记录 `literature/screening_log.csv`；正式同行评议文献进入 `core_library.csv`，预印本进入 `frontier_watchlist.csv`。填写DOI/arXiv/正式链接、审读深度、证据等级、局限和核验日期，不把摘要阅读标为已读全文。运行 `python scripts/validate_library.py`；不因更新入口删除历史证据矩阵及笔记。

## 代码与实验

正式代码进入 `code/src/evcf/`，参数进入 `code/configs/`，新功能补最小单元测试。数据原文件、完整预测、模型权重、密钥和受限全文不提交Git。外部代码记录来源、许可与固定版本，不盲目复制。

实现版本、结果版本、配置SHA与数据snapshot都要记录。任务修订保留前后对账，禁止以硬编码旧统计维持PASS。数据处理口径变化先由主控明确授权；未经批准不改模型、指标或实验边界。

## 分支与合并

优先复用已有任务分支；示例 `data/<task>`、`experiments/<task>`、`docs/<task>`、`fix/<task>`、`lit/<paper-id>-review`。已有名称不为统一格式而重命名。

本地Codex更新原PR后停止，主控依据代码、科学口径、结果与对应HEAD的CI决定是否合并。文档整理不进入正在执行的数据分支。不得直接推送main、force push或清理用户原工作区。
