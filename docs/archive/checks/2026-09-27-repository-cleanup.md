# 仓库清理清单与结果 · 2026-09-27

> 执行方式：当前会话逐项执行，完成后独立只读复核。清单与结果保存在同一文件，避免重复文档。

**目标：** 清理有充分证据的闲置内容，保持页面、文案、交互及有效能力不变。

**方法：** 静态引用用于筛选；再检查 Vue 动态加载、命名空间访问、后端框架注册与 CLI 入口。仅删除已确认无使用者的内容，并复用行为一致的现有 JSON 解析函数。

**技术栈：** Vue 3 / TypeScript / npm，FastAPI / Python 3.12 / uv。

**需求依据：** 用户本轮仓库清理要求及项目根目录 `AGENTS.md`。

## 约束与复核重点

个人数据库、工作目录、Skills、`.workbuddy` 记忆与密钥禁止清理。前后核对受保护文件的路径与 SHA-256，不对正式数据库运行迁移或回滚。

页面组件、路由、文案与交互保持不变。只移除无引用组件及其专属闲置 CSS；用现有测试、构建和桌面截图对比核查。

依赖变更只能经过 npm 或 uv；所有直接依赖都查到用途时保留原声明和锁文件。API 后端接口即使前端没有调用，也可能是公开入口，不因前端封装闲置而删除。

JSON 解析必须继续拒绝重复字段、NaN 与 Infinity。比较旧实现与复用后的实现，并运行 Runtime 与评测相关测试。

保留迁移链、动态调用的服务方法、Pydantic 验证器、框架回调、命令行入口、许可证及独有历史验收证据。日期较早不构成删除理由。

## 任务 1：核查代码、依赖和文档

- [x] 扫描组件、导出、Python 定义、依赖与重复函数体。
- [x] 核查 `import()`、Vue 注册与动态组件、命名空间属性调用、`getattr`、框架装饰器、配置及 CLI。
- [x] 核对候选文档的独有内容与入链。

| 候选 | 证据 | 决定 |
| --- | --- | --- |
| `frontend/src/components/BrandMark.vue` | 项目没有导入、标签或动态注册；现有侧栏品牌使用自己的 SVG | 删除 |
| `main.css` 中 `.brand-symbol`、`.welcome-brand` 专属规则 | 仅闲置 BrandMark 和旧欢迎品牌样式出现这些类；Markdown 禁用原始 HTML | 删除 4 条规则 |
| 前端 `saveMcp` / `McpSave`、`previewMcpImport` / `McpImportPreview` | 仅定义和未使用的测试 mock；新增与编辑页调用 `importMcpJson`、`updateMcpJson` | 删除封装、类型和闲置 mock；保留后端接口 |
| 前端 `folders` / `Folder` / `FolderListing` | 源码与测试无消费者；上下文栏命名空间访问固定为 `chooseFolder`、`syncArchive` | 删除前端封装与类型；保留后端接口 |
| 评测评分 JSON 中的重复字段与非有限常量拒绝逻辑 | 与 `agent_runtime.parse_arguments` 的解析参数及函数体一致，评测本来已依赖 Runtime | 复用现有函数，保留评分字段与范围校验 |
| `docs/DESIGN-v2.md`、`docs/design-v2/components.md` | 仅声明已被 `DESIGN.md` 合并或替代，无独有规范，无其他文档入链 | 删除两个跳转页和空目录 |
| `.DS_Store`、Python / pytest / Ruff 缓存、`frontend/dist/` | 系统元数据或可重建产物，均已忽略；限应用源码目录中的明确路径 | 检查完成后清理 |

## 任务 2：按证据执行最小清理

涉及文件：上表列明的前端代码、`frontend/tests/mcp.test.ts` 和 `backend/app/services/evaluations.py`。只删除闲置定义 / mock / CSS，评分解析改为调用 `parse_arguments(raw)`，不新增业务入口或模块。

- [x] 删除闲置代码、两份替代文档与重复解析逻辑。
- [x] 运行直接相关的前端与后端测试，并完成前端构建。
- [x] 检查文档链接、截图和受保护文件摘要。
- [x] 按明确路径清理可重建产物，独立只读复核并记录实际结果。

## 保留内容

前端 5 项运行依赖、8 项开发依赖，后端 14 项运行依赖、2 项开发依赖均有源码、测试、配置或启动命令用途。MCP SDK 用于协议模型 / 环境 / 版本校验；Uvicorn 为 CLI 入口；jsdom 是 Vitest 的环境配置。未找到可安全删除的直接依赖，不改清单或锁文件。

保留 `ModulePage.vue`，它是路由显式 fallback，项目约定要求未开发模块共用占位页。保留 `textImport.ts`，附件导入继续调用其验证。保留 AppIcon 的注入 fallback、第三方图标的 LICENSE / NOTICE，以及 Alembic 动态发现的全部迁移。

历史审查、差距分析与 `outputs/` 验收报告包含独有分析或当时的验证证据，保留。前端重复错误处理、后端写事务、取消、锁、权限与脱敏逻辑的上下文不同，本次不扩大重构范围。

## 实际结果

已删除 3 个版本库文件：`BrandMark.vue` 和上表两份已替代的文档。其余源码变更为删除 3 个闲置前端 API 封装、4 个配套类型、4 条闲置 CSS 规则、2 个闲置 mock，以及将评测中的重复 JSON 解析逻辑改为复用现有函数。后端公开 API 未删。

清理 125 个忽略文件，共 2,376,357 字节（约 2.27 MiB）。按明确路径删除，没有遍历或清理个人目录：

| 内容 | 实际清理范围 |
| --- | --- |
| 7 个 `.DS_Store` | 项目根目录、`frontend/`、`frontend/src/`、`backend/`、`backend/app/`、`backend/app/repositories/`、`backend/migrations/` |
| 8 个 `__pycache__` 目录 | `backend/app/` 及其 api、schemas、repositories、services 子目录，`backend/tests/`、`backend/migrations/` 及 versions 子目录 |
| 测试与检查缓存 | `backend/.pytest_cache/`、`backend/.ruff_cache/` |
| 可重建产物 | 本次构建生成的 `frontend/dist/`；后续运行 `npm run build` 会重新生成 |
| 空文档目录 | 两份文档删除后为空的 `docs/design-v2/` |

删除前确认目标无符号链接或硬链接，Python 缓存只含字节码，构建目录只含生成文件。`workspace/` 内的 `.DS_Store` 与 Skills、`tool-workspace/`、`.workbuddy/`、数据库和密钥均未清理。`node_modules/` 与 `.venv/` 是当前运行环境，保留。

### 检查结果

| 实际检查 | 结果 |
| --- | --- |
| `npm run test -- tests/mcp.test.ts tests/context-toolbar.test.ts tests/api.test.ts tests/app.test.ts` | 4 个文件、31 项测试通过 |
| `npm run build` | TypeScript 与生产构建通过 |
| `uv sync --locked` | 通过，依赖声明与锁文件未改 |
| `uv run ruff check --no-cache .` | 通过 |
| `uv run ruff format --check --no-cache .` | 93 个文件通过 |
| `uv run pytest tests/test_evaluations.py tests/test_agent_runtime.py tests/test_database.py -q -p no:cacheprovider` | 52 项测试通过；含临时数据库迁移往返与一致性验证 |
| 新旧评分解析对比 | 22 组输入的结果、异常类型和消息一致；覆盖重复字段、NaN / Infinity、边界、越界、布尔值及无效结构 |
| 浏览器与截图 | 14 张 1440×900 截图和初始 Git 基线逐像素一致；无脚本错误、失败 API、页面错误提示或整页横向溢出 |
| 受保护数据 | 核对原有 12 个文件的路径与 SHA-256，全部不变；没有访问或清理正式主密钥 |
| 变更范围 | 全部页面、路由、当前使用的组件、交互代码、文案、依赖声明、锁文件、迁移保持原样 |
| 文档引用与差异 | 现有 Markdown 相对文件链接均有效；`git diff --check` 通过 |
| 独立只读复核 | 未发现遗漏引用或行为变更；复核未修改仓库 |

浏览器与测试使用临时数据库、临时主密钥、独立工具与 Skills 目录；未调用真实供应商或启动用户 MCP。截图沿用 [初始基线](../baseline/2026-09-27/README.md) 的空状态、表单与只读详情，未生成假模型或运行成绩。临时服务已关闭。

未运行两端全量测试；检查按本次变化选择。原有主 JavaScript 包超过 500 kB 的构建提示，以及 TestClient 两条依赖弃用警告保留，本次不升级依赖或调整打包策略。

结构化检查及可重建文件删除清单见 [核查记录](2026-09-27-repository-cleanup.checks.json)。本次变更保留在工作区供查看，未新增 Git 提交，未上传 GitHub。
