# Codex 前端接手交接文档

## 目的

这份文档用于让后续 Codex 直接接手当前 AgentCoin Web 工作台的前端产品化主线，重点覆盖 Compose 终端、自动 ACP 编排、侧栏 agent 选择，以及隐藏式 workflow-room 协作语义。

它取代旧版本里“Codex 只做后端、不碰前端”的约束。当前这条工作线已经进入前后端联动的产品实现阶段，后续接手者需要同时理解前端交互、运行时元数据和后端 workflow 语义。

## 当前产品方向

### 1. 对用户保持一键协作体验

- Compose 仍然是默认入口。
- 用户默认只需要输入任务、选择文件、必要时点选一个或多个 agent。
- 不要把 workflow DAG、leader election、fanout、merge、room policy 等内部概念直接暴露给首次用户。

### 2. 协作语义必须服从白皮书

- 不再把多 agent 协作实现成“群聊 prompt”。
- 当前正确方向是：一个根任务 + 隐藏的 workflow-room 元数据 + 临时 leader / soft leader 语义。
- 编排信息目前写入任务 payload 的 `_workflow_room`、`_runtime.collaboration` 和 `_runtime.acp_prompt`。

### 3. ACP 链路默认自动完成

- Compose 投递本地任务后，会在后台自动尝试 start、open、initialize、list/load、task-request、apply-task-result。
- 手动 ACP 操作仍保留，但默认藏在高级配置后面。
- 对用户来说，结果应直接回写到终端历史，不要求用户理解 ACP 细节。

### 4. 终端结果要带 agent ASCII 标识

- 自动 ACP 成功、超时或失败后的最终回写，现在都允许带执行 agent 的 ASCII glyph。
- 终端输出目标形态是“图标:结果”，而不是“系统提示 + 单独结果块”。
- 不要删除现有保留的 AI ASCII / 像素风图标资产；终端 glyph 是新增的文本化表达，不是替换侧栏图标。

## 已完成状态

### Compose / Workflow UX

- `generic` 已从首次使用路径隐藏，只作为默认 fallback kind。
- Compose 底部 dock 已收口为终端风格，无多余标题和说明文案。
- 工作流 modal 已与 Compose 草稿状态解耦，不再共享 prompt、kind、attachments。
- Compose 本地 notice 已改成短暂浮现，不再常驻挂屏。

### ACP 自动编排

- 已实现自动选择唯一可用 agent，优先命中 GitHub Copilot。
- 已实现自动 start/open/initialize/list/load/task-request/apply-task-result。
- ACP 自动回写结果已经进入终端 history，而不是只停留在侧栏状态或 ACP 面板里。

### 多 agent 产品语义

- 侧栏 agent 卡片支持单选 / 多选。
- 当前默认实现不再为每个 agent 明面上创建一个独立前端任务副本。
- 前端仍只创建一个根 task，再用隐藏 `_workflow_room` / `_runtime.collaboration` 元数据表达参与成员、产品模式和 soft leader 策略。

### 终端结果回显

- `web/src/app/[locale]/page.tsx` 里的 terminal history 已扩展为可选 agent glyph 的 message entry。
- 自动 ACP 最终结果会按 agent glyph + 内容渲染，而不是统一走 `> message`。
- 当前 glyph 使用 ASCII box 风格，与工作台终端视觉一致。

## 当前实现抓手

后续继续改这条线，优先从下面几个位置入手：

- `web/src/app/[locale]/page.tsx`
  - `handleDispatchMultimodalTask`
  - `autoRouteTaskThroughAcp`
  - `pushTerminalSystemMessage`
  - `terminalAgentBadgeForCard`
  - Compose terminal history render
- `web/src/messages/zh.json`
- `web/src/messages/en.json`
- `web/src/messages/ja.json`
- `agentcoin/node.py`
  - `_acp_prompt_text_from_task`
  - workflow fanout / task normalization 路径
- `agentcoin/store.py`
  - `create_subtasks`
  - `summarize_workflow`
  - `finalize_workflow`
  - `apply_external_task_result`

## 关键行为约束

### 1. 不要回退到假数据或演示性 agent 卡片

- 右侧 AI subsystem 卡片必须来自真实 `localManagedRegistrations` / `localAcpSessions`。
- `localDiscoveryItems` 只能补充标题、摘要和命中保留图标资源，不能独立生成虚构 agent 卡片。

### 2. 不要暴露底层编排术语

- 用户可见文案优先用“自动协作执行”“当前由 X 处理”这类产品文案。
- 不要把 `workflow-room`、`leader_strategy`、`fanout` 直接显示给首次用户。

### 3. 所有 UI 文案必须完整随 locale 切换

- 修改 `Workspace` 相关文案时，必须同步维护 `zh / en / ja` 三份 messages。
- 除协议名、产品名、专有名词外，不要混入其他语言。

### 4. 保留 ASCII 视觉资产

- 侧栏 AI agent 图标属于项目要求保留的核心视觉资产。
- 可以重排、复用、迁移，但不能删除，也不要换成普通占位头像。

### 5. 当前真正的 swarm 语义仍然在后端工作流能力上

- 前端现在只是先把复杂度藏起来。
- 若后续继续做多 agent 真正分工，应优先接已有 backend workflow / fanout 能力，而不是继续堆 prompt engineering 假装协作。

## 当前已知技术事实

### ACP 结果回写

- 终端历史此前只有 `{ type, content }`。
- 现在已经扩成可选 agent glyph / agent name 的 entry。
- 自动 ACP 最终回写应优先走这个结构；普通系统日志仍保持 `> message`。

### 图标来源

- 侧栏保留图标由 `preservedAiIconKeyForIdentity(...)` 命中。
- 当前支持的 key：`copilot`、`codex`、`claude`、`openclaw`。
- 终端 glyph 不是直接复用 ReactNode 卡片图，而是映射为 ASCII box。

### workflow 语义

- 根任务已能归一化出 `workflow_id = task.id`。
- 后端已有 `/v1/workflows/fanout`、`create_subtasks(...)`、`summarize_workflow(...)`、`finalize_workflow(...)`。
- 当前前端只是先把 room / leader / fanout 作为隐藏元数据表达，还没有把真实 fanout 全量产品化接出来。

## 后续优先顺序

1. 如果继续提升多 agent 协作真实性，优先把隐藏 workflow-room 逐步接到现有 backend workflow / fanout 能力上。
2. 如果继续优化终端结果展示，保持“agent glyph : result”的直接表达，不要退回纯系统日志口吻。
3. 如果继续拆 `page.tsx`，优先保持行为不变，把 Compose / Node / Swarm 类似 Wallet 那样逐步拆组件。
4. 如果遇到 ACP 异常帧、error frame 或 server session 推断问题，先确认是 live daemon 陈旧问题还是仓库代码问题，再决定改前端还是改后端。

## 建议验证方式

前端改完后至少做下面两步：

```powershell
cd web
npm exec tsc --noEmit
```

如果需要确认页面路由仍可用，再补一次本地页面访问检查，至少确认当前语言页能返回 200。

## 接手前先读

- `docs/whitepaper/zh-CN.md`
- `docs/project/overview.md`
- `docs/architecture/alignment-gap.md`
- `docs/architecture/dispatch-scoring.md`
- `docs/project/frontend-copilot-backend-integration.md`
- `docs/project/frontend-next-slice-roadmap.md`
- `web/src/app/[locale]/page.tsx`

## 一句话交接

继续把 AgentCoin Web 做成“对用户像一键终端协作，对系统内部仍然是 workflow-room + soft leader + 可演进 fanout”的产品，不要把复杂编排概念直接甩到界面上。
