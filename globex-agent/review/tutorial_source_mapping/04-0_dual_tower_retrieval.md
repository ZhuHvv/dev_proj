# 04-0 LLM双塔向量召回与语义检索

> [钉钉原文](https://docs.dingtalk.com/i/nodes/DnRL6jAJMGp7P2mlhqQvbZ2qWyMoPYe1) · 当前结论：**已落地**。

## 教程概念与源码

| 阶段 | 当前实现 |
| --- | --- |
| 文本向量化 | [openai_embedding_client.py](../../app/infrastructure/embedding/openai_embedding_client.py) |
| 商品向量索引 | [qdrant_product_index.py](../../app/infrastructure/vector/qdrant_product_index.py) |
| 查询编排 | [catalog_search.py](../../app/application/usecases/catalog_search.py) |
| 接口隔离 | Domain/Application 中的 `EmbeddingClient`、`ProductVectorIndex` 端口 |

## 真实调用链

[批量向量化](../../app/infrastructure/embedding/openai_embedding_client.py#L39) → [Qdrant 写商品向量](../../app/infrastructure/vector/qdrant_product_index.py#L43)。查询侧由 [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) 发起：query 文本 → [Embedding](../../app/infrastructure/embedding/openai_embedding_client.py#L36) → [Qdrant cosine 搜索](../../app/infrastructure/vector/qdrant_product_index.py#L58) → product_id → 商品仓库补全实体 → 过滤/排序/卡片组装。

“双塔”在本项目中体现为商品文本和用户 query 使用同一个向量空间；仓库没有训练双塔模型，只有调用 Embedding 推理服务的客户端。

## 数据、副作用与降级

- Qdrant 保存向量和 product_id 载荷，完整商品仍以商品仓库为准。
- 向量召回失败不会让搜索完全不可用，`CatalogSearchUseCase` 可退化到关键词 2-gram 路径。
- Embedding 可由 Redis 缓存，减少重复请求；缓存键包含模型/文本语义。

## 验证入口

用 [run_product_recall.py](../../scripts/eval/run_product_recall.py) 比较 `embedding_only` 与 `keyword_2gram`，不要只凭单个查询主观判断召回质量。
