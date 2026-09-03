# 13 CategoryInsight品类洞察工具与RAG商品知识库

> [钉钉原文](https://docs.dingtalk.com/i/nodes/wva2dxOW4YPD3NrMfkeXNoOXVbkz3BRL) · 当前结论：**已落地**。

## 两套检索不要混淆

`product_search` 检索结构化商品索引；`category_insight` 检索 [knowledge](../../knowledge/) 下的品类知识文档。工具入口在 [category_insight_tool.py](../../app/application/tools/category_insight_tool.py)，RAG 实现在 [category_knowledge.py](../../app/infrastructure/rag/category_knowledge.py)。

## 真实链路

启动时：[构造知识库](../../app/infrastructure/rag/category_knowledge.py#L34) → [bootstrap 文档切片与幂等入库](../../app/infrastructure/rag/category_knowledge.py#L61) → Embedding → 知识 collection。

请求时：[Main/SearchAgent 工具集](../../app/application/agents/search_agent.py#L57) → [category_insight 工具](../../app/application/tools/category_insight_tool.py#L31) → embedding → 知识 collection top-K → 带来源片段的 `ToolChunk` → Agent 基于证据回答。

## 数据、副作用与失败

- 启动建库会写向量存储，但不修改商品/订单数据。
- 知识库初始化失败只降级该能力，不阻止整个服务启动。
- 工具结果应保留来源，模型没有证据时应明确边界，不能把常识补全伪装成知识库事实。

## 与教程的连接

本章的 RAG（Retrieval-Augmented Generation，检索增强生成）是品类知识问答；商品排序的向量召回属于 04/11/13-1，二者 collection、数据模型和评测指标都不同。
