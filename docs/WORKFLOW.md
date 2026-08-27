# Research Workflow

## 文献流

`检索 → 去重 → 摘要筛选 → 全文审读 → 证据提取 → 缺口映射 → 可检验假设`

每篇P0全文建议建立一个Issue，使用 `paper-review.yml` 模板；全文读完后更新：

- CSV状态为 `reviewed-full`；
- 对应note；
- `gap_map.md`；
- 必要时新增复现实验Issue。

## 数据流

`许可核验 → 下载 → checksum → schema审计 → 清洗报告 → 划分协议 → 基线`

禁止在清洗前先决定模型输入，也禁止对测试期使用全数据统计量。

## 实验流

`问题假设 → baseline → small gate → ablation → robustness → locked result`

每项实验必须记录：

- 数据版本和划分；
- Git commit；
- 配置文件；
- 随机种子；
- 环境；
- 结果文件checksum；
- 失败原因和停止规则。
