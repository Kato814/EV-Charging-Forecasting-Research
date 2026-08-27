# Contributing

## 文献新增

新增文献必须：

1. 先写入 `literature/screening_log.csv`；
2. 正式同行评议文献进入 `core_library.csv`；预印本进入 `frontier_watchlist.csv`；
3. 填写 DOI/arXiv/正式链接、审读深度、证据等级、已知局限和核验日期；
4. 不得将“看过摘要”标记为“已读全文”；
5. 运行 `python scripts/validate_library.py`。

## 代码新增

- 所有正式代码进入 `code/src/evcf/`；
- 实验参数必须进入 `code/configs/`，不得只写在 notebook；
- 新功能需要最小单元测试；
- 数据原文件、模型权重、密钥和付费 PDF 不提交 Git；
- 外部代码优先作为依赖、submodule 或固定 commit 的独立克隆，不直接复制进仓库。

## 分支命名

- `lit/<paper-id>-review`
- `data/<dataset-id>-audit`
- `exp/<experiment-name>`
- `method/<module-name>`
- `fix/<issue>`

## Commit 示例

```text
lit(P0034): add full-text evidence on flexibility forecasting

data(D0003): document CHARGED field audit and license

exp: add leave-one-city-out seasonal-naive baseline
```
