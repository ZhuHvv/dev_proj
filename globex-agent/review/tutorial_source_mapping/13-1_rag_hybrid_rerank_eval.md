# 13-1 RAG召回精排进阶：数据生产·Hybrid·Rerank·评测

> [钉钉原文](https://docs.dingtalk.com/i/nodes/pYLaezmVNe26kznBHPL0324zWrMqPxX6) · 当前结论：**部分落地**。

## 已落地组件

- 向量召回：[openai_embedding_client.py](../../app/infrastructure/embedding/openai_embedding_client.py) + [qdrant_product_index.py](../../app/infrastructure/vector/qdrant_product_index.py)。
- 精排：[http_reranker.py](../../app/infrastructure/rerank/http_reranker.py)。
- 查询编排：[catalog_search.py](../../app/application/usecases/catalog_search.py)。
- 指标：[metrics.py](../../scripts/eval/metrics.py) 与 [run_product_recall.py](../../scripts/eval/run_product_recall.py)。

## 当前链路

[seed 商品](../../app/infrastructure/persistence/seed_products.py#L215) → [Embedding](../../app/infrastructure/embedding/openai_embedding_client.py#L36) / [Qdrant](../../app/infrastructure/vector/qdrant_product_index.py#L58) → query 向量 top-N → [optional Reranker](../../app/infrastructure/rerank/http_reranker.py#L22) → top-K → [Recall@K/MRR/NDCG](../../scripts/eval/metrics.py#L108) 评测。向量失败时有独立关键词 2-gram 降级，但它没有与向量结果融合。

## 教程中未落地的关键点

当前检索范围内没有 BM25 + dense vector 的 Hybrid（混合召回），也没有 RRF（Reciprocal Rank Fusion，倒数排名融合）。因此不能把“存在关键词降级”描述成“已实现 Hybrid”。

## 数据与风险

训练/标注数据主要是 seed 与离线 JSONL；候选生产策略改变后必须重跑门禁。Reranker 故障会静默退化到 embedding-only，所以评测报告必须分策略统计。
