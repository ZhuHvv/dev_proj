# 第31章：Docker Compose 与 K8s × 源码

- 钉钉原文：[第31章-Docker Compose 全栈与 K8s 可选](https://docs.dingtalk.com/i/nodes/dxXB52LJqnM0N5xEUZ6gb5ql8qjMp697)

## 已落地的本地基础设施

[`docker-compose.yaml`](../../docker/docker-compose.yaml#L1) 编排 MySQL、Redis、RocketMQ 等中间件；[`init.sql`](../../docker/init.sql#L1) 初始化业务表；[`init-mq.sh`](../../docker/init-mq.sh#L1) 准备 Topic/消费组。在线应用和 worker 仍从 Maven/Spring Boot 单独启动，不是全部制作成 Compose 服务镜像。

## 默认配置关系

在线进程连接 MySQL `3307`、Redis `6380`、RocketMQ Proxy `8081`；worker 使用同一数据库/Redis但独立连接池和 workerId，见两份 `application.yaml`。

## K8s 状态

仓库没有 Dockerfile、Helm Chart 或 Kubernetes Deployment/Service/ConfigMap/Secret 清单。K8s（Kubernetes，容器编排平台）是教程的可选生产化演进，不是已交付部署物。多副本前还要先解决 WebSocket 事件路由、调度任务竞争、配置/密钥和可观测性。

