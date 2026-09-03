# 钉钉教程 × Globex 本地源码：逐篇索引

> 基准：2026-09-03 当前工作区。这里不是按主题合并的摘要，而是严格按钉钉“项目教程”的 39 篇文档，一篇教程对应一个本地 Markdown 文件。
>
> 证据约定：`已落地` 表示能在当前仓库找到实际接线；`部分落地` 表示只有部分能力或等价实现；`仓库外` 表示教程内容属于训练/基础设施侧；`待实现` 表示当前检索范围内没有找到实现。教程描述目标，源码决定当前事实。

## 阅读方法

每篇都按同一组问题展开：教程在解决什么问题、源码入口在哪里、真实调用链如何走、数据怎样变化、有哪些副作用与失败路径、当前实现与教程有什么差异。第一次阅读建议先走 [09 项目总览](09_project_bootstrap.md) → [15 前后端闭环](15_fastapi_frontend.md) → [14 Supervisor-Workers](14_supervisor_workers.md) → [11 商品检索工具](11_product_search_tool.md)。

## 39 篇一一对应

| 教程篇章 | 本地源码解读 | 当前结论 |
| --- | --- | --- |
| 01 AgentLoop范式与电商搜索Agent核心概念 | [01](01_agentloop_core.md) | 等价落地 |
| 02 AgentLoop快速入门与多轮工具调用 | [02](02_agentloop_tool_loop.md) | 已落地 |
| 03-0 主AgentLoop按需派发子Agent的策略与三件事判断 | [03-0](03-0_dispatch_strategy.md) | 已落地，软路由 |
| 03-1 技术栈与多Agent架构选型 | [03-1](03-1_multi_agent_architecture.md) | 已改线为 AgentScope |
| 04-0 LLM双塔向量召回与语义检索 | [04-0](04-0_dual_tower_retrieval.md) | 已落地 |
| 04-1 向量基础设施选型与OpenSearch演进方向 | [04-1](04-1_vector_infrastructure.md) | 部分落地 |
| 04-2 Embedding训练与Reranker精排 | [04-2](04-2_embedding_reranker.md) | 推理已落地，训练仓库外 |
| 05 Cache-Breakpoint上下文压缩与缓存治理 | [05](05_context_cache.md) | 已落地 |
| 06 长期记忆与用户偏好Store | [06](06_long_term_memory.md) | 已落地 |
| 07 AGUI事件协议与WebSocket实时推送 | [07](07_agui_websocket.md) | 自定义等价实现 |
| 08 Rubric评测与Agentic-RL训练闭环 | [08](08_rubric_rl_loop.md) | 评测已落地，训练未闭环 |
| 08-1 Agent SFT 冷启动训练全流程 | [08-1](08-1_agent_sft.md) | 仓库外 |
| 08-2 Agentic RL 训练全流程 | [08-2](08-2_agentic_rl.md) | 仓库外 |
| 09 Globex项目总览与工程初始化 | [09](09_project_bootstrap.md) | 已落地 |
| 09-1 多平台商品数据底座：合规采买、同构与指标加工 | [09-1](09-1_product_data_foundation.md) | 部分落地 |
| 10 基础模块与模型配置 | [10](10_model_configuration.md) | 已落地 |
| 11 ProductSearch商品检索工具与子Agent派发触发场景 | [11](11_product_search_tool.md) | 已落地 |
| 12 到手价内联计算与关税运费规则 | [12](12_landed_price.md) | 已落地，静态规则 |
| 13 CategoryInsight品类洞察工具与RAG商品知识库 | [13](13_category_insight_rag.md) | 已落地 |
| 13-1 RAG召回精排进阶：数据生产·Hybrid·Rerank·评测 | [13-1](13-1_rag_hybrid_rerank_eval.md) | 部分落地 |
| 13-2 商品检索召回评测：标注集·三指标·降级链对比 | [13-2](13-2_recall_evaluation.md) | 已落地 |
| 14 主AgentLoop组装与Supervisor-Workers协同机制 | [14](14_supervisor_workers.md) | 等价落地 |
| 15 FastAPI接口与前后端闭环 | [15](15_fastapi_frontend.md) | 已落地 |
| 16-1 Docker Compose 全栈编排与环境锁定 | [16-1](16-1_docker_compose.md) | 已落地 |
| 16-2 vLLM推理服务与GPU部署 | [16-2](16-2_vllm_gpu.md) | 仅调用边界 |
| 16-3 可观测性体系与LangFuse全链路Trace | [16-3](16-3_observability.md) | OTel 等价实现 |
| 16-4 Token预算管理与模型路由降级 | [16-4](16-4_token_budget_routing.md) | 部分落地 |
| 16-5 工具熔断与请求排队优先级 | [16-5](16-5_breaker_queue.md) | 已落地 |
| 16-6 安全护栏与K8s生产化 | [16-6](16-6_security_k8s.md) | 护栏部分落地，K8s 未落地 |
| 17-1 Harness工程全景与Globex组件映射 | [17-1](17-1_harness_mapping.md) | 部分落地且接线不完整 |
| 17-2 Middleware-Hook-Pipeline与工具调用生命周期 | [17-2](17-2_middleware_pipeline.md) | 等价落地 |
| 17-3 单步验证与Silent-Drift漂移检测 | [17-3](17-3_drift_detection.md) | 部分落地 |
| 17-4 动态工具权限与对话阶段状态机 | [17-4](17-4_permissions_state_machine.md) | 权限部分落地，状态机不实现 |
| 18 Bad-Case驱动的数据飞轮 | [18](18_bad_case_flywheel.md) | 待实现 |
| 19-1 系统提示词架构与分级强调 | [19-1](19-1_system_prompt.md) | 基础版已落地 |
| 19-2 工具与子 Agent 提示词与决策路由 | [19-2](19-2_tool_agent_prompt.md) | 已落地 |
| 19-3 缓存友好写法与元提示词 | [19-3](19-3_cache_friendly_prompt.md) | 缓存友好已落地，元提示词未落地 |
| 19-4 Globex 主子Agent系统提示词全文与逐层注解 | [19-4](19-4_prompt_annotation.md) | 已落地 |
| 19-5 Agent Skill 渐进式能力加载 | [19-5](19-5_agent_skill_loading.md) | 待实现 |

## 跨篇阅读

跨篇的请求主链请看 [02 一次用户请求的完整调用链追踪](../02_core_call_chain.md)，项目骨架请看 [01 项目总览与核心文件定位](../01_project_overview.md)。上述两篇只承担总览，不替代 39 篇独立文档。
