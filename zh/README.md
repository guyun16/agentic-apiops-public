# Agentic APIOps

基于 Java 执行平台、Python AgentLab 和 React 控制台的 API 测试与诊断项目。
Java 负责正式执行、鉴权、项目隔离和 TestReport；Python 负责生成、诊断、
受控工具编排、Trace 与评估。

[English](../README.md) · [公开文档](../docs/README.md) · [HR 演示](../docs/hr-demo.md)

## 可以查看什么

- OpenAPI 导入、TestCase DSL 生成、编辑和 Java 校验。
- 异步执行、取消、重跑、请求响应快照及报告导出。
- 失败诊断、人工审批、历史恢复与 Trace；项目资源访问始终经过 Java 授权。
- 中英文控制台、项目隔离及独立 HR 演示账号初始化。
- APIOps Bench 的 14 次完整 Full105 历史和 1,470 个任务结果。

![系统架构](../.github/assets/agentic-apiops-architecture.svg)

## Benchmark 结果

| 运行 | PASS | FAIL | UNKNOWN |
| --- | ---: | ---: | ---: |
| Portfolio v5 | 95 | 9 | 1 |
| Diagnosis Contract v2 | 94 | 8 | 3 |

两次运行使用不同契约，不能混合或当作受控模型对比。14 次历史中包含 12 次
real-model adapter 运行和 2 次混合 fixture 基线。它是项目自建数据集上的评估，
不代表通用模型排行榜或生产可靠性。失败和未知结果保留；本次发布没有重新调用
模型或修改成绩。详见[结果解释](../docs/benchmark-design.md)和
[发布策略](../docs/benchmark-publication.md)。

## 运行与检查

依赖 Java 21、Python 3.11+/uv、Node 22/npm 和 Docker。Java 默认测试使用
Testcontainers；真实模型验证需要单独配置，未运行的门控检查不能算作通过。

按[开发环境](../docs/README-dev-env.md)安装和启动；已配置的 Windows 工作区可使用
[本地启动器](../docs/local-start.md)。[HR 演示工具](../docs/hr-demo.md)创建随机密码、
专用账号和真实成功/失败记录。仓库没有可供公开登录的固定密码。

公开版本包含源码、普通测试、合成 fixture、必要说明、正式发布结果包及少量回归
证据。原始服务日志、本地数据库、凭据及无关中间实验未公开。回归样本公开副本中
的机器路径被规范化，并记录原始和公开副本哈希；正式发布结果包字节不变。历史
来源标识保留，当前可读取文件以发布 manifest 为准。

目前不支持自动触发诊断或浏览器中的 Java 诊断；Python 诊断锁与恢复面向单机
SQLite 部署。当前公开版本的实际检查结果见英文首页的 Verification。
