# 第03章：Maven 多模块与依赖倒置 × 源码

- 钉钉原文：[第03章-Maven 多模块骨架与依赖倒置](https://docs.dingtalk.com/i/nodes/dxXB52LJqnM0N5xEUZ6gy4Qp8qjMp697)
- 本地补充：[模块结构](../../README.md#L82)

## 模块骨架

根 [`pom.xml`](../../pom.xml#L13) 聚合 `dash-shared`、`dash-domain`、`dash-application`、`dash-infrastructure`、`dash-presentation`、`dash-bootstrap`、`dash-worker`、`dash-bench` 八个模块；Java 版本固定为 21，Spring Boot、RocketMQ、Sentinel、ShardingSphere 版本由根工程统一管理。

## 真实启动点

在线进程从 [`CampusDashApplication`](../../dash-bootstrap/src/main/java/com/campusdash/CampusDashApplication.java#L16) 启动，后台进程从 [`WorkerApplication`](../../dash-worker/src/main/java/com/campusdash/worker/WorkerApplication.java#L27) 启动。二者用不同 `worker-id` 创建雪花 ID，见在线 [`snowflakeIdGenerator()`](../../dash-bootstrap/src/main/java/com/campusdash/CampusDashApplication.java#L27) 与 worker [`WorkerBeans`](../../dash-worker/src/main/java/com/campusdash/worker/WorkerBeans.java#L16)。

## 依赖规则如何验证

[`ArchitectureRuleTest`](../../dash-domain/src/test/java/com/campusdash/domain/ArchitectureRuleTest.java#L1) 用 ArchUnit（架构单元测试）守住 domain 不反向依赖 Spring/JDBC/Redis；这比只在文档画箭头更可靠。

## 阅读建议

不要按模块逐个横扫。选一个用例，按 presentation → application → domain port/model → infrastructure adapter → SQL/Lua → test 纵向阅读，才能看到依赖倒置如何落地。

