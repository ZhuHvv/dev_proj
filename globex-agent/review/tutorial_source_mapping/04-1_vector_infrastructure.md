# 04-1 向量基础设施选型与OpenSearch演进方向

> [钉钉原文](https://docs.dingtalk.com/i/nodes/dxXB52LJqnM0N5xEUKDRErX98qjMp697) · 当前结论：**部分落地**；当前是 Qdrant，未找到 OpenSearch 实现。

## 当前架构边界

[qdrant_product_index.py](../../app/infrastructure/vector/qdrant_product_index.py) 实现 `ProductVectorIndex` 端口；[composition.py](../../app/composition.py) 根据配置组装服务端 Qdrant 或本地/禁用形态；[docker-compose.yaml](../../docker/docker-compose.yaml) 提供 Qdrant 服务。

## 真实链路

[Settings/Composition 组装](../../app/composition.py#L129) → [Qdrant collection 就绪检查](../../app/infrastructure/vector/qdrant_product_index.py#L36) → [写商品向量](../../app/infrastructure/vector/qdrant_product_index.py#L43) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) → [Qdrant 返回 id 与 score](../../app/infrastructure/vector/qdrant_product_index.py#L58) → 商品仓库补全。

## 数据与运维影响

- collection 的向量维度必须与 Embedding 模型一致；改模型不能只改名称，还需重建索引。
- Qdrant 不保存价格、库存等完整业务真相，避免向量库替代交易数据库。
- 服务不可用时走关键词降级，因此“请求成功”不等于“向量检索健康”，需要同时观察 `search_strategy`。

## 与教程的差异

OpenSearch、BM25 与向量 Hybrid 是演进方向，不是当前事实。端口抽象让以后替换成为可能，但新增实现仍需处理索引迁移、双写、回滚和评测门禁。
