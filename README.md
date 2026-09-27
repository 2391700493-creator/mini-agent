# Mini Agent

**基于轻量 Harness 的本地 Agent 工作台。**

连接模型，配置助手，在聊天中完成任务，再通过运行记录和评测检查效果。面向学习和开发 Agent 应用的人，使用 Vue 3、FastAPI 与 SQLite 构建。

这里的 Harness 是 Agent 的运行内核：负责模型与工具循环、上下文管理、执行限制、取消和事件记录。聊天与评测共用这套内核。

[快速开始](#快速开始) · [通用助手案例](examples/general-assistant/README.md) · [架构与代码入口](docs/架构说明.md) · [评测指南](docs/第一次评测.md)

## 核心能力

| 能力 | 实现 |
| --- | --- |
| **统一运行** | 聊天与评测共用 Agent Runtime，支持流式回复、多轮工具调用、停止与执行预算 |
| **按需扩展** | 组合模型、本地工具、Skills 和 MCP；Skill 按需加载，工具调用时重新校验权限 |
| **观察与验证** | 查看运行事件、工具结果、耗时和 Token 用量；用数据集评测并复核失败项 |

连接模型 → 配置 Agent → 聊天执行 → 查看运行 → 评测改进

## 快速开始

下载源码并进入项目目录。准备 Node.js 22.12+、npm 和 uv；Python 3.12 由 uv 管理。在两个终端分别运行：

```sh
# 终端一：后端，初始化 SQLite 并启动服务
cd backend
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```sh
# 终端二：前端
cd frontend
npm ci
npm run dev
```

打开 [本地工作台](http://127.0.0.1:5173)，连接自己的 Chat Completions 兼容模型。测试成功后，点击“用这个模型创建 Agent”，填写名称和指令，即可开始对话。首次使用无需配置 MCP 或 Skills。

模型调用使用你自己的 API Key，可能产生费用。需要工具调用时，请选择支持该能力的模型。详细配置见 [使用指南](docs/使用指南.md)。

## 从通用助手开始

[通用助手案例包](examples/general-assistant/README.md) 提供系统提示词、资料整理 / 任务规划 / 出行查询三个 Skill，以及高德 MCP 的配置步骤。你可以先体验资料整理，再按需加入地图查询和本地文件处理。

例如：

> 整理这段会议记录，提取决定与待办，不补充缺失信息：“小王周五前整理用户反馈；小李负责界面方案，时间未定；上线日期待确认。”

案例需要按说明导入并绑定能力，不包含模型密钥或本机数据库。示例任务用于体验流程，不代表已经验证的性能结果。

## 架构与验证

前端使用 Vue 3、TypeScript、Vite、Pinia 和原生 CSS；后端使用 Python 3.12、FastAPI、SQLAlchemy、SQLite 和 Alembic。

```text
frontend/src/               页面、组件与状态
backend/app/services/       Agent Runtime、能力执行、运行记录与评测
backend/app/repositories/   数据访问
backend/tests/              隔离数据库与模拟模型测试
frontend/tests/             页面交互测试
examples/general-assistant/ 可复用的助手配置与 Skills
docs/                       架构、使用与评测说明
```

技术细节和核心代码入口见 [架构说明](docs/架构说明.md)，开发约定与检查命令见 [AGENTS.md](AGENTS.md)。

评测复用聊天的 Runtime，可使用内置的三条基础示例熟悉流程，再导入自己的问题与标准。项目不预置虚构的性能成绩，测试通过也不等于模型任务成功率。操作步骤见 [第一次评测](docs/第一次评测.md)。

## 使用范围

当前提供源码启动方式，面向本地单用户，默认仅监听本机。MCP 支持本机 stdio；Shell 仅支持具备可用沙箱的 macOS。文件操作限制在授权目录，Skills 提供指令，不直接执行代码。模型未返回用量时，相关统计保留缺失状态。

配置、会话和运行记录保存在本地 SQLite，Skills 保存在本地文件。模型密钥和 MCP 环境变量加密保存；数据库与项目外主密钥需分别备份。数据库、密钥和个人工作文件不应提交到 GitHub，具体路径与备份说明见 [使用指南](docs/使用指南.md)。

## 参考项目

流程组织参考 [Open Agent Platform](https://github.com/langchain-ai/open-agent-platform)，简明架构表达参考 [nanobot](https://github.com/HKUDS/nanobot)，运行观察参考 [AgentScope Studio](https://github.com/agentscope-ai/agentscope-studio)，评测组织参考 [promptfoo](https://github.com/promptfoo)。上述参考用于流程与信息组织，未移植这些仓库的代码。
