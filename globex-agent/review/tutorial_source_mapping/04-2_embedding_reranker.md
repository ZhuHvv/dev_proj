# 04-2 Embedding训练与Reranker精排

> [钉钉原文](https://docs.dingtalk.com/i/nodes/MyQA2dXW7eqzZpbkHZlNEENkJzlwrZgb) · 当前结论：**Embedding/Reranker 推理已接，训练未落地**。

## 当前源码对应

- [openai_embedding_client.py](../../app/infrastructure/embedding/openai_embedding_client.py)：调用兼容 Embedding API。
- [http_reranker.py](../../app/infrastructure/rerank/http_reranker.py)：调用外部精排 HTTP 服务。
- [catalog_search.py](../../app/application/usecases/catalog_search.py)：先召回候选，再按配置精排。
- [settings.py](../../app/infrastructure/settings.py)：模型名、地址和开关。

## 真实调用链

[CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) → [query Embedding](../../app/infrastructure/embedding/openai_embedding_client.py#L36) → [top-N Qdrant 候选](../../app/infrastructure/vector/qdrant_product_index.py#L58) → [HTTP Reranker](../../app/infrastructure/rerank/http_reranker.py#L22) → 重排 top-K → 业务过滤与商品卡片。未配置 `RERANKER_BASE_URL` 或调用失败时，策略退化为 `embedding_only`。

## 数据与副作用

推理只改变候选次序，不修改商品数据；外部调用会增加延迟、费用和故障面。评测报告需要记录实际策略，否则 reranker 失效后仍可能看到“有结果”而误判正常。

## 与教程的差异

当前仓库没有 Embedding 或 Reranker 的训练数据生成、训练任务、checkpoint、模型注册与发布代码。相关章节应映射为“外部模型生产线 + 本仓推理适配器”，不能说训练闭环已经实现。
