# 13-2 商品检索召回评测：标注集·三指标·降级链对比

> [钉钉原文](https://docs.dingtalk.com/i/nodes/OG9lyrgJPzZXGaRKhlYyA57EWzN67Mw4) · 当前结论：**已落地**。

## 数据与脚本

[product_recall.jsonl](../../eval/product_recall.jsonl) 是标注查询集；[run_product_recall.py](../../scripts/eval/run_product_recall.py) 构造各检索策略并运行；[metrics.py](../../scripts/eval/metrics.py) 计算 Recall@K、MRR 和 NDCG 并执行门禁。

## 真实评测链

[读取 JSONL 与构造策略](../../scripts/eval/run_product_recall.py#L70) → `embedding_rerank / embedding_only / keyword_2gram` → [逐 query 获取 ranked ids](../../scripts/eval/run_product_recall.py#L135) → [计算聚合指标](../../scripts/eval/metrics.py#L108) → 与阈值比较 → [报告/退出码](../../scripts/eval/run_product_recall.py#L197)。

## 三指标在本项目中的意义

- Recall@K：相关商品是否进入前 K，衡量“有没有找回来”。
- MRR：首个相关商品有多靠前，衡量用户多久看到第一个有效答案。
- NDCG：多个相关商品的整体排序质量。

## 失败与边界

外部 Embedding、Qdrant 或 Reranker 不可用会影响相应策略；脚本应明确报告失败/降级，不能混入正常样本。当前标注集基于种子商品，不能直接代表生产多平台流量。

## 与在线链路连接

离线策略必须对应 [catalog_search.py](../../app/application/usecases/catalog_search.py) 的实际分支。若线上增加过滤、偏好或到手价排序，也要在评测数据与断言中覆盖。
