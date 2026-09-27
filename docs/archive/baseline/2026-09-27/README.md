# Mini Agent 初始基线 · 2026-09-27

本次建立本地 Git 基线，记录已有页面、功能和基础检查结果。未修改业务代码、数据库模型或迁移，未调用真实模型、执行 MCP 程序或上传 GitHub。

## 提交与敏感文件核查

项目原先没有 Git 仓库。本次初始化 `main` 分支，提交作者按用户提供的信息设置在当前仓库内，不修改全局 Git 配置，不配置远端。

核查覆盖提交候选源码、测试、文档、示例及本地数据文件的名称、链接属性和文本内容。扫描不输出凭据值；检查私钥标记、常见供应商令牌、带认证信息的 URL 和疑似硬编码密钥。四处命中经人工核对，均为测试占位值或表单校验提示，未发现真实凭据。模式扫描不能证明不存在所有形式的秘密。

现有数据库及辅助文件、会话 Markdown 副本、已导入的 Skills 和 `.workbuddy` 记忆属于本机数据，不进入提交。保留 `backend/.env.example` 和 `examples/general-assistant/` 中可复用的示例。

| 类型 | 提交处理 |
| --- | --- |
| `backend/data/`、SQLite 数据库、WAL / SHM / journal | 忽略，保留本机文件 |
| `.env`、`.env.*` | 忽略，允许 `.env.example` |
| `.key`、`.pem`、`.p12`、`.pfx` | 新增忽略规则 |
| `tool-workspace/`、`workspace/` | 忽略本机工作文件及已导入 Skills |
| `.workbuddy/` | 新增忽略规则，排除个人记忆 |
| `node_modules/`、`.venv/`、缓存、构建输出、日志 | 沿用忽略规则 |
| 源码、迁移、测试、依赖锁文件、设计与使用文档、案例、既有验收报告 | 纳入初始版本 |

使用 `git check-ignore` 核对上述规则及 `.env.example` 例外。源文件扫描范围内没有发现符号链接或硬链接文件。应用主密钥默认位于项目外；本次未读取或修改其内容。

执行前后逐文件计算 SHA-256，已有文件中仅 `.gitignore` 变化；业务代码、依赖锁文件、正式数据库及其 WAL / SHM、个人工作文件均保持原样。本次新增内容仅为此基线文档、检查记录和截图。

## 页面与导航

路由依据 `frontend/src/router/index.ts` 和 `modules.ts`；页面状态来自本次隔离环境的实际浏览器访问。`/` 跳转到 `/chat`。侧栏提供新建对话、Agent 管理、能力工坊、观察评测、定时任务、项目和历史对话，并支持折叠与搜索。

| 页面 | 路由 | 本次记录的状态与入口 |
| --- | --- | --- |
| 聊天 | `/chat` | 无 Agent 的引导、消息输入区、附件入口、项目与历史对话 |
| Agent 管理 | `/agents` | 空状态、新建 Agent 入口 |
| 新建 / 编辑 Agent | `/agents/new`、`/agents/:id/edit` | 名称、模型、说明、任务指令、能力绑定、高级设置；本次打开新建页 |
| 模型连接 | `/models` | 空状态、添加模型入口 |
| 添加 / 编辑模型 | `/models/new`、`/models/:id/edit` | 服务地址、模型名称、API Key；高级参数和价格记录默认折叠；本次打开添加页 |
| 本地工具 | `/tools` | 当前时间、Shell、文件读写三项卡片；时间启用，其余停用 |
| 工具详情 | `/tools/:id` | 参数、限制、调用示例；本次打开 `/tools/current_time` |
| 任务技能 | `/skills` | 空状态、刷新、ZIP 导入和格式说明 |
| 编辑 Skill | `/skills/:id/edit` | 路由与页面已存在；未导入测试技能，未访问编辑页 |
| 外部工具 | `/mcp` | 空状态、连接入口和说明 |
| 新增 / 编辑 MCP | `/mcp/new`、`/mcp/:id/edit` | JSON 配置导入入口；本次打开新增页，未导入或启动程序 |
| 运行记录 | `/runs` | 状态、Agent、模型、来源和时间筛选；空记录提示 |
| 运行详情 | `/runs/:id` | 路由与页面已存在；没有运行数据，未访问详情页 |
| Agent 评测 | `/evaluations` | 数据集 / 任务切换、内置三条基础示例；打开了示例数据集详情 |
| 定时任务 | `/automations` | 空状态与创建入口；未创建任务 |

所有当前一级业务模块均绑定了具体页面。共用 `ModulePage.vue` 保留在代码中，本次没有把它记作已开发功能。

## 核心功能

以下功能通过现有源码与专项文档核对。浏览器检查仅覆盖页面入口、空状态和只读详情；没有逐项执行真实模型任务。

| 功能 | 当前实现与主要入口 |
| --- | --- |
| 模型管理 | Chat Completions 兼容连接、参数与价格记录、连接测试、默认模型、Fernet 加密；`services/model_connection.py`、`services/secrets.py` |
| Agent 配置 | 模型、指令、工具 / Skill / MCP 绑定、默认 Agent、提示词版本、显式跨会话记忆；`services/agents.py`、`services/memories.py` |
| 统一执行 | 聊天、定时任务和评测复用 Agent Runtime，支持流式回复、多轮工具调用、执行预算、停止及上下文压缩；`services/agent_runtime.py` |
| 聊天与附件 | SQLite 会话与消息、累积 SSE 快照、Agent 切换、重新生成、反馈、图片 / PDF / 文本附件；`services/chat.py`、`services/attachments.py` |
| 项目与本地工作目录 | 会话分组、授权目录选择与绑定、Markdown 副本及同步重试；`services/workspace.py` |
| 本地工具 | 时间、受 macOS 沙箱约束的 Shell、授权目录内文件读写，统一执行入口；`services/tool_execution.py` |
| Skills | ZIP 导入、刷新、编辑、启停、删除、摘要冲突检查及按需加载；`services/skills.py` |
| MCP | 本机 stdio 配置、连接测试与工具发现、环境变量加密、启停与引用保护；`services/mcp.py` |
| 运行观察 | 运行记录与事件、工具结果、耗时、Token 和成本信息；`services/runs.py` |
| 评测 | 数据集、用例、模型评分与过程规则、失败项重跑和人工复核；`services/evaluations.py` |
| 定时任务 | 后端调度、启停、手动运行、停止，结果保存为普通会话；`services/automations.py` |

当前是本地单用户应用，不包含账号体系、云同步或团队协作。真实模型兼容性、模型效果、MCP 服务和操作系统沙箱执行均不在本次验收范围内。

## 截图与浏览器检查

截图来自新建临时 SQLite 数据库和独立的密钥、工具、Skills 目录。未复制正式数据库或个人配置，未填入假模型、假 Agent、假回复或假运行成绩；评测中的三条用例由应用现有初始化逻辑提供。

使用独立 Chrome 浏览器上下文，视口 **1440×900**、缩放 1、中文、Asia/Shanghai。共保存 14 张首屏截图；长表单的折叠内容与下方内容不一定出现在首屏。没有手机尺寸检查。

| 截图 | 页面 |
| --- | --- |
| [01-chat.png](screenshots/01-chat.png) | 聊天空状态 |
| [02-agents.png](screenshots/02-agents.png) | Agent 管理空状态 |
| [03-models.png](screenshots/03-models.png) | 模型连接空状态 |
| [04-model-new.png](screenshots/04-model-new.png) | 添加模型 |
| [05-agent-new.png](screenshots/05-agent-new.png) | 新建 Agent |
| [06-tools.png](screenshots/06-tools.png) | 三项本地工具及默认启停状态 |
| [07-skills.png](screenshots/07-skills.png) | 任务技能空状态 |
| [08-mcp.png](screenshots/08-mcp.png) | 外部工具空状态 |
| [09-mcp-new.png](screenshots/09-mcp-new.png) | MCP JSON 配置入口 |
| [10-runs.png](screenshots/10-runs.png) | 运行记录筛选与空状态 |
| [11-evaluations.png](screenshots/11-evaluations.png) | 评测数据集入口 |
| [12-automations.png](screenshots/12-automations.png) | 定时任务空状态 |
| [13-tool-detail.png](screenshots/13-tool-detail.png) | 当前时间工具详情 |
| [14-evaluation-dataset.png](screenshots/14-evaluation-dataset.png) | 内置基础示例详情 |

14 次页面记录均未出现浏览器脚本错误、页面错误提示、失败 API 响应或整页横向溢出。通过页面链接打开工具详情、通过按钮打开基础评测示例，并验证根路由跳转。`/api/health` 返回 HTTP 200，`status=ok`、`database=connected`。结构化证据见 [browser-checks.json](browser-checks.json)。

浏览器控制工具两次超时，后改用已安装的 Playwright 与系统 Chrome 的独立上下文。临时启动脚本第一次缺少后端导入路径，补充临时进程的 `PYTHONPATH` 后正常启动；未更改应用启动代码。采集结束后关闭此次启动的前后端服务。

## 实际运行的基础检查

环境：Node.js 24.19.0、npm 12.0.2、uv 0.12.5、Python 3.12.14；安装后的 TypeScript 为 5.9.3，vue-tsc 为 3.3.11。检查结果见 [checks.json](checks.json)。

| 工作目录 | 命令 | 结果 |
| --- | --- | --- |
| `backend/` | `uv sync --locked` | 通过，锁文件不变 |
| `frontend/` | `npm ci` | 通过，锁文件不变；安装审计报告 0 个已知漏洞 |
| `frontend/` | `npm run test` | 18 个测试文件、140 项测试通过 |
| `frontend/` | `npm run build` | TypeScript 检查与 Vite 生产构建通过 |
| `backend/` | `uv run ruff check .` | 通过 |
| `backend/` | `uv run ruff format --check .` | 93 个文件格式通过 |
| `backend/` | `uv run pytest tests/test_health.py tests/test_database.py -q` | 7 项测试通过 |
| `backend/` | `uv run alembic upgrade head` | 临时数据库升级到 `c50746eb95cd` |
| `backend/` | `uv run alembic check` | 未检测到新增迁移操作 |

数据库相关测试已在临时数据库执行升级、回滚到 base、再次升级及模型一致性检查。未对正式数据库迁移或回滚。未运行后端全量测试，本次没有改动业务逻辑。

保留以下现有警告，未为消除警告修改代码或依赖：

- Vite 主 JavaScript 包压缩后约 536.61 kB，超过默认 500 kB 提示阈值。
- Starlette TestClient 提示 `httpx` 与 `BlockingPortal` 相关弃用信息，共两条。
- `npm ci` 按当前 npm 策略阻止可选依赖 `fsevents` 安装脚本；安装、测试和构建均成功，未放宽脚本策略。
- 全量 `git diff --cached --check` 在既有 `docs/Agent-UI-交互审查-2026-09-15.md` 第 3、4、17、18 行报告行尾空格，属于原有 Markdown 双空格换行，按原样保留；仅检查本次新增文档与 `.gitignore` 时通过。

既有 `docs/`、`outputs/` 中的审查与验收文档按原样保留，其历史结论不视为本次重新验证的结果。
