# HR 演示 / Recruiter showcase

演示使用独立的 `hr-showcase` 项目和两个账号：`hr-presenter` 为 OWNER，
`hr-viewer` 为 VIEWER。初始化生成随机密码，保存在已忽略的
`.local-run/hr-demo/.env.local`，不提供公共固定密码。

## 初始化

先按[开发环境](README-dev-env.md)配置数据库、Java 平台（19090）、订单服务
（18080）、Python（18000）和 Console（5173）。确保 Console 的 Python 代理指向
18000，根 `.env.local` 包含本机 `APIOPS_AUTH_DB_URL`、`APIOPS_AUTH_DB_USERNAME`
和 `APIOPS_AUTH_DB_PASSWORD`。Java 已构建，Python 虚拟环境位于
`python-apiops-agentlab/.venv`。

```powershell
.\scripts\setup-hr-demo.ps1 -SkipStart
```

已完成[Windows 启动器配置](local-start.md)的机器可以省略 `-SkipStart`。
脚本创建专用账号及项目，通过 Java API 导入
[订单服务 OpenAPI](openapi/demo-order-service-openapi.json)，执行两个真实 GET 查询，
检查报告、账号隔离、只读权限和 14 条已发布 Benchmark 历史。已有数据会复用；
账号密码、角色或项目归属不匹配时停止，不覆盖已有账号。

## 展示顺序

1. **API Studio**：查看导入的订单服务接口和 TestCase DSL。
2. **Runs 成功记录**：`HR Demo: product list succeeds`，实际 HTTP 200 与断言一致。
3. **Runs 失败记录**：`HR Demo: intentional assertion failure`，故意期望 HTTP 201，
   实际返回 200，用于解释断言失败和诊断入口。
4. **已有范例**：[成功 DSL](../examples/testcase-valid.json)、
   [缺少 token](../examples/testcase-missing-token-valid.json)、
   [非法数量](../examples/testcase-invalid-quantity-valid.json)、
   [诊断报告](../examples/diagnosis-report-valid.json)。这些是契约示例；使用时需要
   调整项目、API 标识符和运行环境，不能当作本机真实运行记录。
5. **APIOps Bench**：展示 14 次完整历史。v5 为 **95 PASS / 9 FAIL / 1 UNKNOWN**；
   Diagnosis Contract v2 为 **94 / 8 / 3**，属于另一契约，不能拼接成绩。

初始化只查询已有商品数据，不调用模型，不伪造 Trace 或诊断。用户主动启动生成或
诊断时才会使用对应的模型配置。VIEWER 不能提交执行；Benchmark 是公共只读结果。
实际项目 ID 和运行 ID 由本机初始化产生，记录在 `.local-run/hr-demo/demo-summary.json`。

The script provisions isolated presenter/viewer identities, generates local passwords,
and seeds real success/failure examples through Java APIs. It does not copy development
accounts, publish credentials, call a model or manufacture historical results. See
[Benchmark interpretation](benchmark-design.md) for evidence scope and limitations.
