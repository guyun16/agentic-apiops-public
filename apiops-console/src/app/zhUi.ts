// Console-owned copy only. API payloads, identifiers and source evidence stay intact.
export const zhUi: Record<string, string> = Object.fromEntries(`
Draft restored. Validate it with Java before running.|已恢复草稿，执行前请先通过 Java 校验。
Select an endpoint|选择接口
Select an endpoint to inspect its Java metadata.|选择接口以查看 Java 平台中的元数据。
Loading endpoint metadata...|正在加载接口元数据…
Reading the selected endpoint from Java Platform.|正在从 Java 平台读取所选接口。
Endpoint metadata unavailable|接口元数据不可用
Unable to load endpoint metadata.|无法加载接口元数据。
Endpoint Detail|接口详情
TestCase Workspace|测试用例工作区
Refresh|刷新
Benchmark API unavailable; retry after the service recovers.|基准测试接口不可用，请在服务恢复后重试。
APIOps Bench|APIOps 基准测试
Verified formal runs|已验证的正式运行
Full-105 Benchmark History|完整 105 任务基准测试历史
Diagnosis Result|诊断结果
DiagnosisReport is not available for this execution.|本次执行暂无诊断报告。
Select a diagnosis execution from History.|请从历史记录中选择一次诊断。
Agent run|智能体运行
Choose a diagnosis execution to inspect its real result.|选择一次诊断以查看实际结果。
Reading the real DiagnosisReport from Python AgentLab.|正在从 Python AgentLab 读取诊断报告。
Loading Diagnosis Result|正在加载诊断结果
The diagnosis result API is unavailable.|诊断结果接口不可用。
Diagnosis Result unavailable|诊断结果不可用
All Runs|全部运行
No diagnosis is known in this Console session yet.|当前会话中暂无已知诊断。
Group by|分组方式
Failure Type|失败类型
No executions|暂无执行记录
Selective Execution|选择运行并诊断
TestCase|测试用例
Java Report|Java 报告
Loading TestReport|正在加载测试报告
Report unavailable|报告不可用
Current State|当前状态
Ready to diagnose|可以开始诊断
Refresh saved diagnosis|刷新诊断状态
Starting Diagnosis…|正在启动诊断…
Start Diagnosis|开始诊断
View Run Report|查看运行报告
Java Platform browser diagnosis is not wired. No diagnosis request will be sent.|Java 平台尚未接入浏览器诊断，暂不可用。
Start Diagnosis is available only for failed or timed-out runs.|只有失败或超时的运行可以启动诊断。
Checking saved diagnoses before starting…|正在检查已保存的诊断…
The Python workflow is paused for human approval.|Python 工作流已暂停，等待人工审批。
Python AgentLab is ready to run against this Java TestReport.|Python AgentLab 已就绪，可根据此 Java 测试报告诊断。
Select a run from All Runs to inspect its execution evidence.|从全部运行中选择一项，查看执行证据。
Python AgentLab Evaluation|Python AgentLab 运行评估
Runtime Agent Run analysis only. Evaluation and Benchmark remain separate; runtime facts, deterministic evaluation, and model-based evaluation are not interchangeable.|此处仅分析智能体运行。运行评估与基准测试独立展示，运行事实、规则评估和模型评估分别记录。
Reading runtime facts from Python AgentLab.|正在从 Python AgentLab 读取运行事实。
Loading Runtime Evaluation|正在加载运行评估
The Python runtime evaluation API could not be reached.|无法连接 Python 运行评估接口。
Loading selected runtime facts...|正在加载所选运行事实…
No runtime run matches the current filters.|没有符合当前筛选条件的运行。
No runtime Evaluation runs are available for this project.|此项目暂无可评估的运行。
Evaluation workspace|评估工作区
Select a runtime run to inspect its Evaluation workspace.|选择一次运行以查看评估。
Resolving existing business context...|正在解析已有业务上下文…
Evaluation adds analysis only; it does not add Context Trail nodes.|评估仅提供分析，不会新增上下文链路节点。
No linked business context was resolved for this Agent Run.|未找到此智能体运行关联的业务上下文。
Monitor system health and recent activity across your APIOps workflows.|查看 APIOps 工作流的系统健康状态和最近活动。
All rights reserved.|保留所有权利。
Reading observed AgentLab trace records for the current project.|正在读取当前项目的 AgentLab 追踪记录。
Loading traces|正在加载追踪记录
The trace read API is unavailable.|追踪读取接口不可用。
Traces unavailable|追踪记录不可用
No observed trace records exist for the current project.|当前项目暂无追踪记录。
Selected Step Details|所选步骤详情
Previous|上一项
Next|下一项
Step ID|步骤编号
Ended At|结束时间
Input Parameters|输入参数
Tool Result|工具结果
No type-specific facts are available.|暂无此类型的专属事实。
Agent Step ID|智能体步骤编号
Related Links|相关链接
ToolResult Status|工具结果状态
Has Data|包含数据
Source Run ID|来源运行编号
Agent Run ID|智能体运行编号
Workflow Type|工作流类型
Current Trace|当前追踪
Execution Waterfall|执行瀑布图
Observed execution timing and step hierarchy|实际执行耗时与步骤层级
Waterfall legend|瀑布图图例
Step Name|步骤名称
Click a step in the waterfall to view details.|点击瀑布图中的步骤查看详情。
Total Duration|总耗时
No case results recorded.|暂无用例结果。
Assertions summary|断言汇总
Diagnose|诊断
Step details|步骤详情
TestReport facts for the selected step.|所选步骤的测试报告事实。
Select a step to inspect its TestReport facts.|选择步骤以查看测试报告事实。
TestReport detail tabs|测试报告详情页签
Step details will appear when TestReport is available.|测试报告可用后将显示步骤详情。
Runs List|运行列表
Run status|运行状态
Execution Overview|执行概览
Evaluation Coverage|评估覆盖情况
Runtime Facts|运行事实
Execution facts were recorded.|已记录执行事实。
Deterministic Evaluation|规则评估
Token Usage|词元用量
Provider usage was recorded.|已记录模型服务用量。
Runtime cost was recorded.|已记录运行成本。
At a Glance|概览
runtime runs|次运行
No runtime runs match the current filters.|没有符合当前筛选条件的运行。
Runtime execution failed.|运行执行失败。
NOT EVALUATED|未评估
Evaluation is analysis only and does not change execution facts or Java authorization. Runtime facts, deterministic scores, and model-based Judge opinions remain separate.|评估仅用于分析，不改变执行事实或 Java 授权。运行事实、规则评分和模型评审意见分别展示。
Rule-based evaluation requires a persisted EvaluationResult correlated to this Agent Run.|规则评估需要关联此智能体运行的已保存评估结果。
Persisted EvaluationResult|已保存的评估结果
Evaluation ID|评估编号
Evaluator version|评估器版本
Ground Truth|标准答案
Ground Truth version|标准答案版本
No formal EvaluationCase and Ground Truth were available, so no accuracy score was inferred from Trace facts.|暂无正式评估用例和标准答案，因此不会从追踪事实推算准确率。
Model-based semantic evaluation remains separate from deterministic and execution facts.|模型语义评估与规则评估、执行事实分别展示。
Judge result ID|模型评审结果编号
Rubric version|评分标准版本
Judge model|评审模型
Model version|模型版本
Prompt version|提示词版本
Judge is model-based evaluation.|模型评审由模型进行评估。
Judge is not run automatically to fill this page.|此页面不会自动触发模型评审。
Judge does not change execution facts.|模型评审不改变执行事实。
Judge does not authorize tools.|模型评审不授予工具权限。
Observed execution facts from Python AgentLab; these are not Evaluation scores.|来自 Python AgentLab 的实际执行事实，不作为评估分数。
Runtime identity|运行标识
Validation|校验
Validation is N/A for Diagnosis runs and is never rendered as numeric zero.|诊断运行不适用此校验项，不会显示为数值零。
Tool Execution|工具执行
These are observed ToolIntent / ToolResult outcomes, not Tool Accuracy.|此处是实际工具意图与结果，不代表工具准确率。
Safety|安全性
A Python runtime ALLOW observation does not replace Java Tool Gateway authorization.|Python 运行中的允许记录不能替代 Java 工具网关授权。
An explicit runtime safety outcome was recorded.|已记录明确的运行安全结果。
Runtime timing and provider usage retain their original VALUE, UNKNOWN, ERROR, or N/A semantics.|运行耗时和模型用量保留原始的有值、未知、错误或不适用状态。
Recorded runtime fact.|已记录的运行事实。
The frontend does not infer provider pricing. Missing versioned runtime pricing remains UNKNOWN.|前端不推算模型服务价格；缺少带版本的运行定价时显示为未知。
Select Runtime|选择运行环境
Browser execution not wired|尚未接入浏览器执行
Not wired|尚未接入
Real workflow · metadata appears after start|实际工作流，启动后显示元数据
Real|实际执行
Workflow|工作流
Python AgentLab only|仅限 Python AgentLab
Availability|可用性
Unavailable for Java Platform|Java 平台暂不可用
Workflow steps will appear after Start Diagnosis.|启动诊断后将显示工作流步骤。
Supporting Evidence|支撑证据
Context Characters|上下文字符数
Java TestReport|Java 测试报告
Not loaded|未加载
The selected run TestReport is loading or unavailable.|所选运行的测试报告正在加载或暂不可用。
Assertion Mismatch / Failure|断言不匹配／失败
Assertion did not pass.|断言未通过。
Failure recorded by Java TestReport.|Java 测试报告记录的失败。
No assertion mismatches or failure facts are recorded.|暂无断言不匹配或失败记录。
Environment / Runtime|环境／运行时
Execution authority|执行平台
Metadata appears after Start Diagnosis|启动诊断后显示元数据
Human Approval|人工审批
Real workflow intent|实际工作流意图
Approval Required|等待审批
Report not available|暂无报告
Result history|结果历史
Diagnosis History|诊断历史
Search diagnosis|搜索诊断
Search diagnosis...|搜索诊断…
Diagnosis history list|诊断历史列表
Loading Diagnosis History|正在加载诊断历史
Diagnosis History unavailable|诊断历史不可用
Retry|重试
No diagnosis executions for current project|当前项目暂无诊断记录
No diagnosis executions match the current filters|没有符合当前筛选条件的诊断
Diagnosis history pagination|诊断历史分页
Sufficient Evidence|证据充分
Limited Evidence|证据有限
Evidence unavailable|证据不可用
Diagnosis result actions|诊断结果操作
Open Source Run|查看来源运行
Project ID|项目编号
Finished At|完成时间
The execution is readable, but Python AgentLab did not return a structured DiagnosisReport.|可以读取执行记录，但 Python AgentLab 未返回结构化诊断报告。
Diagnosis Summary|诊断摘要
Evidence-backed reasoning|基于证据的推理
Root Cause Hypotheses|根因假设
Hypothesis|假设
Evidence reference from DiagnosisReport|诊断报告中的证据引用
The real DiagnosisReport did not return a root-cause hypothesis.|诊断报告未返回根因假设。
Recommended Checks|建议检查项
No recommended checks were returned.|未返回建议检查项。
Result boundaries|结果适用范围
Limitations|局限性
No limitations were returned.|未返回局限性说明。
failed assertions|条失败断言
Evidence and context appear here when a real DiagnosisReport is selected.|选择诊断报告后，此处将显示证据和上下文。
Failed case evidence|失败用例证据
TestReport cases|测试报告用例
Failed Assertions|失败断言
No failed case facts are present in this TestReport.|此测试报告中暂无失败用例事实。
No case facts are present in this TestReport.|此测试报告中暂无用例事实。
calls|次调用
PASS / (PASS + FAIL); UNKNOWN and N/A excluded|通过数／（通过数＋失败数）；不含未知和不适用项
VALUE samples|有效数值样本
No saved ratio metrics are available.|暂无已保存的比率指标。
Executed Tasks|已执行任务
Counts from the complete persisted task response. Select a type to inspect its task metrics.|数量来自已保存的完整任务响应。选择类型以查看任务指标。
Unrecognized task type|无法识别的任务类型
Dataset Info|数据集信息
Dataset total size is not provided; selected tasks are this run only.|未提供数据集总量；所选任务仅属于本次运行。
Execution mode|执行模式
Metric Definitions|指标定义
Task Success Rate|任务成功率
Saved diagnosis_accuracy: exact match with expected diagnosis or an accepted alternative; VALUE samples only.|已保存的诊断准确率：与预期诊断或可接受替代答案精确匹配，仅统计有效数值样本。
Valid JSON Rate|JSON 有效率
Saved valid_json: JSON parsing validity; VALUE samples only. Does not establish executability.|已保存的 JSON 有效性：仅验证解析有效，仅统计有效数值样本，不代表可执行。
Safety Violation Count|安全违规次数
Count not exposed by the result API|结果接口未提供次数
Units and availability|单位与可用性
Rates use %. Count, latency and cost are not plotted. N/A, UNKNOWN, MISSING, ERROR and numeric zero remain distinct.|比率使用百分比，次数、延迟和成本不绘入此图。不适用、未知、缺失、错误与数值零分别展示。
Recent Benchmark Runs|最近基准测试运行
COMPLETED describes execution, not a PASS verdict.|已完成表示执行结束，不代表判定通过。
Current result identity|当前结果标识
Revision|修订版本
Verified v5 artifact snapshot · API does not expose final outcome fields. Refresh reads historical APIs; this sealed snapshot stays pinned.|已验证的 v5 产物快照。接口未提供最终结果字段；刷新会读取历史接口，固定快照保持不变。
Search tasks|搜索任务
Task category|任务类别
All types|全部类型
Formal outcome|正式结果
All outcomes|全部结果
Filters affect this task list only; official run scores remain unchanged.|筛选仅影响任务列表，正式运行分数保持不变。
No tasks match the current filters.|没有符合当前筛选条件的任务。
No failure reason provided|未提供失败原因
Task detail|任务详情
Task Schema|任务结构
Final v5 source evidence|v5 最终来源证据
Verified artifact snapshot, not an API response. Only allowlisted facts are bundled; source files are not edited.|已验证的产物快照，不是接口响应。仅包含允许展示的事实，源文件保持不变。
Verified At|验证时间
Published display fields|已发布展示字段
Source paths and SHA-256|源文件路径与 SHA-256
The Task Success Rate definition below describes legacy v1 diagnostics, not the official v5 Pass Rate or Outcome Accuracy.|下方任务成功率定义适用于旧版 v1 诊断，不适用于正式 v5 通过率或结果准确率。
Legacy v1 strict conditions below are diagnostic evidence; the official v5 outcome is shown above.|下方旧版 v1 严格条件用于诊断证据；正式 v5 结果显示在上方。
Saved evaluation conditions below are formal results. No later audit verdict is supplied.|下方已保存的评估条件为正式结果，未提供后续审计结论。
Expected / Actual: not provided by this API.|此接口未提供预期值／实际值。
Metrics and evidence references|指标与证据引用
Official v5 outcome|正式 v5 结果
Persisted outcome metrics|已保存的结果指标
Value|值
Expected metric value|预期指标值
Recorded metric observations are evidence, not a new frontend verdict.|已记录的指标观测值是证据，不是前端重新判定的结果。
Copy failed; select the text to copy.|复制失败，请选中文本后复制。
Final Benchmark Result|最终基准测试结果
OFFICIAL V5 RESULT|正式 V5 结果
Tasks passed|通过任务数
Pass Rate|通过率
Outcome Accuracy|结果准确率
Provider Provenance|模型服务来源
Capability Breakdown|能力分类
Click a capability to inspect task-level evidence.|点击能力类别以查看任务证据。
Remaining Limitations|现存局限
Execution Integrity|执行完整性
Persisted|已保存
Three verified complete runs|三次已验证的完整运行
Verified complete runs|已验证的完整运行
API Browser|接口浏览器
OpenAPI metadata|OpenAPI 元数据
Loading endpoints...|正在加载接口…
API endpoints unavailable|接口列表不可用
Unable to load API endpoints.|无法加载接口列表。
Deprecated|已弃用
Untitled endpoint|未命名接口
No description is documented for this endpoint.|此接口未提供说明。
Quick Example|快速示例
Endpoint example|接口示例
Request Example|请求示例
No request example is documented.|未提供请求示例。
Expected Response Example|预期响应示例
No applicable strategy selected|尚未选择适用策略
No response example is documented.|未提供响应示例。
No Expected Response is available for this strategy.|此策略暂无预期响应。
Select an applicable strategy with documented response evidence.|请选择包含响应证据的适用策略。
Shared TestCase DSL|共享测试用例 DSL
Final TestCase DSL|最终测试用例 DSL
Submitting...|正在提交…
Run Test|执行测试
View|查看
Generation result|生成结果
Accepted|已接受
Submitted to Java Runner|已提交至 Java 执行器
View Run|查看运行
Generate a TestCase to inspect the final shared DSL.|生成测试用例后可查看最终共享 DSL。
Endpoint contract details|接口契约详情
Endpoint detail tabs|接口详情页签
What this endpoint does|接口功能
No description documented.|未提供说明。
Security Contract|安全契约
Declared security requirement|声明的安全要求
No security requirement documented.|未声明安全要求。
Expected Response|预期响应
Expected contract from metadata; not a Runner response.|元数据中的预期契约，不是执行器的实际响应。
Expected HTTP Status|预期 HTTP 状态码
Documented response|已声明的响应
No media type documented|未声明媒体类型
Why this response?|此响应的选择依据
Response schema|响应结构
Response example|响应示例
Expected Response unavailable|预期响应不可用
This strategy has no documented response evidence for the selected endpoint.|所选接口未提供此策略对应的响应证据。
Generate from the selected endpoint|根据所选接口生成
Not configured|未配置
Java|Java
Available strategies are determined from endpoint metadata.|可用策略由接口元数据决定。
Context Trail|上下文链路
Expand Context Trail|展开上下文链路
Collapse Context Trail|收起上下文链路
Project|项目
Global search|全局搜索
Search APIs, endpoints, runs, traces...|搜索 API、接口、运行、追踪…
Reading persisted executions from Java Platform.|正在从 Java 平台读取已保存的执行记录。
Loading runs|正在加载运行记录
Runs unavailable|运行记录不可用
Java Platform returned no persisted executions for this project.|Java 平台未返回此项目的执行记录。
An existing diagnosis is running. Waiting for its saved result…|已有诊断正在执行，正在等待保存结果…
Restored saved diagnosis|已恢复诊断
Calling the real Python Diagnosis Workflow…|正在调用 Python 诊断工作流…
Guardrails paused the real workflow for human approval.|安全检查已暂停工作流，等待人工审批。
The real DiagnosisReport is ready.|诊断报告已就绪。
Edited arguments must be a valid JSON object.|修改后的参数必须是有效的 JSON 对象。
Workflow status|工作流状态
Submitting approval decision…|正在提交审批决定…
The diagnosis worker stopped before saving a result. Start a new diagnosis to retry; previous tool calls are not replayed automatically.|诊断进程在保存结果前中断。可重新开始诊断；之前的工具调用不会自动重放。
A diagnosis for this run is already executing. Refresh its saved status.|此运行已有诊断正在执行，正在刷新已保存状态。
Context Read Model Gap|上下文读取信息缺失
No active context|暂无活动上下文
ROOT|起点
UNIFIED RESULT VIEW|统一结果视图
Spring AI Diagnosis Agent|Spring AI 诊断智能体
TestCase DSL editor|测试用例 DSL 编辑器
Agentic APIOps Console|智能 APIOps 控制台
Agentic API Operations|智能 API 运维
This module is reserved for the next console phase.|此模块将在后续版本提供。
Close|关闭
PASS / selected|通过数／所选任务数
PASS / (PASS + FAIL)|通过数／（通过数＋失败数）
Deterministic result unavailable|规则评估结果不可用
Judge result unavailable|模型评审结果不可用
RUNNING|运行中
COMPLETED|已完成
APPROVAL_REQUIRED|等待审批
FAILED|失败
REJECTED|已拒绝
PENDING|等待中
SUCCESS|成功
ASSERTION_FAILED|断言失败
EXECUTION_FAILED|执行失败
TIMEOUT|超时
CANCELLED|已取消
PASS|通过
FAIL|失败
UNKNOWN|未知
MISSING|缺失
ERROR|错误
N/A|不适用
NOT_REQUESTED|未请求
ALLOW|允许
DENY|拒绝
All|全部
Failed|失败
Ready|就绪
Running|运行中
Diagnosed|已诊断
Low|低
Medium|中
High|高
LOW|低
MEDIUM|中
HIGH|高
Authorization / Guard / Audit|授权／防护／审计
Case → Step|用例 → 步骤
Collapse|收起
Legacy v1 strict conditions|旧版 v1 严格条件
Output (JSON)|输出（JSON）
Task success conditions|任务成功条件
READY|就绪
Ready to start.|可以开始。
Waiting for human approval.|等待人工审批。
DiagnosisReport is ready.|诊断报告已就绪。
Diagnosis execution stopped by the approval decision.|诊断已根据审批决定停止。
Diagnosis execution failed.|诊断执行失败。
Diagnosis workflow is running.|诊断工作流正在运行。
Guardrails require approval before the Java Tool Gateway call.|安全检查要求在调用 Java 工具网关前进行审批。
REQUIRE_APPROVAL|需要审批
Diagnosis Workflow|诊断工作流
workflowId|工作流编号
projectId|项目编号
toolIntentId|工具意图编号
argumentsFingerprint|参数指纹
not created|尚未创建
Run / Revision|运行／修订版本
Contract|契约
PASS / FAIL / UNKNOWN|通过／失败／未知
Unresolved / Ambiguous|未解析／存在歧义
Unresolved|未解析
Multiple endpoints share this operationId.|多个接口使用相同的操作标识。
Endpoint identity is unavailable.|接口标识不可用。
Read through JavaApiOpsClient.|通过 Java API 客户端读取。
ContextPack / RAG|上下文包／检索增强
Project-scoped ContextPack was built by the existing workflow.|工作流已构建当前项目的上下文包。
A real provider call was recorded by TraceRecorder.|追踪记录器已记录实际模型调用。
HITL approval|人工审批
The existing Guardrails policy paused this exact ToolIntent.|安全策略已暂停此工具意图，等待审批。
Java Tool Gateway|Java 工具网关
The Java-owned ToolResult was observed by TraceRecorder.|追踪记录器已记录 Java 返回的工具结果。
DiagnosisReport|诊断报告
Real DiagnosisReport returned by the existing workflow.|工作流已返回实际诊断报告。
TestReport|测试报告
AVAILABLE|可用
VALUE|有值
NOT_APPLICABLE|不适用
DENIED|已拒绝
No tool attempt|未尝试调用工具
no tool attempt|未尝试调用工具
Ground Truth unavailable|标准答案不可用
No persisted JudgeResult|暂无已保存的模型评审结果
Not applicable to this execution type|不适用于此执行类型
Runtime fact|运行事实
Tool Outcome|工具结果
Explicit runtime fact|明确的运行事实
wall clock|实际耗时
model time|模型耗时
total tokens|总词元数
runtime pricing fact|运行定价记录
explicit fact|明确事实
VALID_JSON|JSON 有效
SCHEMA_VALID|结构有效
CONTRACT_ACCEPTED|契约已接受
runId|运行编号
taskId|任务编号
reportId|报告编号
agentRunId|智能体运行编号
traceId|追踪编号
apiId|接口编号
toolCallId|工具调用编号
All validation facts passed|全部校验事实均通过
Wall-clock latency|实际耗时
Model latency|模型耗时
Prompt tokens|输入词元数
Completion tokens|输出词元数
Total tokens|总词元数
Total Runtime|总运行时间
Model Latency|模型延迟
Safety Outcome|安全结果
Formal FAIL|正式失败
UNKNOWN / Uncertain|未知／不确定
Other outcomes / Execution exceptions|其他结果／执行异常
API Studio|API 工作台
TestCases|测试用例
Changes require Java validation before execution.|用例已修改，请先通过 Java 校验再执行。
Current TestCase passed Java validation.|当前用例已通过 Java 校验。
Selected from the endpoint’s documented 2xx responses.|选自接口文档中声明的 2xx 成功响应。
Required request metadata is present and this is the documented validation response.|请求元数据包含必填项，这是文档声明的校验响应。
A request boundary is documented and this is the documented invalid-input response.|文档已声明请求边界，这是对应的无效输入响应。
The endpoint declares security and documents this authentication failure response.|接口已声明安全要求，这是文档中的认证失败响应。
Selected from the endpoint’s documented idempotency-related response evidence.|选自接口文档中与幂等性相关的响应证据。
Selected from the endpoint’s documented non-2xx response mapping.|选自接口文档中声明的非 2xx 响应。
Metadata evidence is not available.|元数据证据不可用。
Requires a documented 2xx response.|需要文档中声明的 2xx 响应。
Requires a documented required request field.|需要文档中声明的必填请求字段。
Requires a documented request boundary.|需要文档中声明的请求边界。
Requires a documented security requirement.|需要文档中声明的安全要求。
Requires explicit idempotency documentation.|需要明确的幂等性说明。
Requires a documented non-2xx response.|需要文档中声明的非 2xx 响应。
Requires a documented Expected Response for this strategy.|需要文档中声明的此策略对应的预期响应。
Today|今天
Earlier|更早
Successful|成功
All statuses|全部状态
Summary|摘要
Runs|运行记录
Success|成功
Cancelled|已取消
Provider|模型服务商
Report|报告
Saved diagnosis unavailable|已保存的诊断不可用
`.trim().split('\n').map(line => {
  const index = line.indexOf('|')
  return [line.slice(0, index), line.slice(index + 1)]
}))

// Only known console-generated templates; never translate arbitrary evidence text.
export function translateDynamicUi(text: string): string | undefined {
  const count = /^(\d+) (SUCCESS|success|UNKNOWN|DENIED|non-success|persisted JudgeResult|validation fact error|validation fact unavailable|validation fact failed)$/.exec(text)
  if (count) {
    const labels: Record<string, string> = {
      SUCCESS: '次成功', success: '次成功', UNKNOWN: '项未知', DENIED: '次拒绝',
      'non-success': '次未成功', 'persisted JudgeResult': '条已保存的模型评审结果',
      'validation fact error': '项校验事实错误', 'validation fact unavailable': '项校验事实不可用',
      'validation fact failed': '项校验事实未通过',
    }
    return `${count[1]} ${labels[count[2]]}`
  }
  const ratio = /^(\d+ \/ \d+) PASS$/.exec(text)
  if (ratio) return `${ratio[1]} 通过`
  const provider = /^(DeepSeek|Qwen) diagnosis$/.exec(text)
  if (provider) return `${provider[1]} 诊断`
  return undefined
}
