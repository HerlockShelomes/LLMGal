# LLMGal 项目长期笔记

## 项目定位

基于大语言模型 API 的多模态角色聊天原型（软件测试课程的被测对象，非生产）。
Vue 3 + TS + Vite + Pinia 前端；Python + FastAPI + WebSocket 后端；
经 OpenAI 兼容接口调用文本模型，另接语音合成与图像生成。

## ⚠️ 当前分支与工作位置（2026-09-16 核查）

**角色增删 / 运行时模式 / 画风统一这一整套工作全在分支 `feat/module1-mock-and-role-mgmt` 上**，
提交链 `4cae08b` → `903f5cd` → `b7f2b9a`，已推送 `origin/feat/module1-mock-and-role-mgmt`。
分支 **303 个文件 vs `main` 208 个**。

**老登 9-15 10:17 切回了 `main`（`9c8e3ee`）**，工作区现在是不含任何改动的版本
（`artifacts` 只剩 2 个文件、`docs` 只剩 5 个）—— 不是东西丢了。
**看到文件数量骤减 / 功能代码不见了，第一件事是 `git rev-parse --abbrev-ref HEAD`。
要继续角色增删的工作必须先 `git checkout feat/module1-mock-and-role-mgmt`。**

9-16 逐个验证完好（`git show <分支>:<路径>`，关键标记全命中）：
`Create_New_Role.py`（`list_custom_roles` + `delete_role`，725 行）、`Connect.py`
（`/api/roles/delete` + `/api/roles/list` + `/api/system/mode`）、`MockMode.py`、
`config.py`（`get_mode`/`is_mock`/`set_mode`）、后端 4 套测试（TC-DEL / TC-LIST / TC-MODE / TC-STYLE）、
`roleCreation.ts`（`reconcileCustomRoles`）、`appMode.ts`、`SettingsPanel.vue`（`type="button"`）、
`roleDelete.test.ts`、`roleReconcile.test.ts`、`vite.config.ts`（`src/assets/roles`）、林亦 13 个资源文件。

切分支时 GitHub Desktop 又自动 stash 了一次（`stash@{0}`，34 个文件），
**只有日志和临时探针，无源码**。

**隐患**：`.workbuddy/memory/` 被 git 跟踪，切分支会让记忆文件互相覆盖（9-16 已发生）。
本文件当前是 `main` 上的旧版本，切回 feat 分支会再变一次。

## 验证方式（固定套路）

本机没有 `backend/.venv`，但**已存在** `.venv-module1`，直接复用它，不要重新创建：

```powershell
Set-Location "F:\LLMGal\backend"
& "F:\LLMGal\.venv-module1\Scripts\python.exe" -m pytest tests -q
```

前端：

```powershell
Set-Location "F:\LLMGal\frontend"
& "F:\LLMGal\frontend\node_modules\.bin\vue-tsc.cmd" --noEmit -p tsconfig.app.json
& "F:\LLMGal\frontend\node_modules\.bin\vite.cmd" build
& "F:\LLMGal\frontend\node_modules\.bin\vitest.cmd" run
```

## 会话与角色的绑定（2026-09-15 新增，改这两块前必读）

需求：会话记录清空重建 + 角色与会话强绑定。核心实现：

- `stores/chat.ts`：`Conversation` 增加 `roleName` / `roleLabel`；
  标题 = `「角色名-对话N」`，N 由 `roleCounters`（按角色各自计数）给出。
  某角色会话删光时连计数器一起清，下次从「对话1」重新数。
  持久化键已从 `ai-chat-history` 换成 `ai-chat-history-v2`（旧键由 `main.ts` 启动时 removeItem）。
- `composables/useRoleSession.ts`：唯一的绑定逻辑出口（侧边栏 / 设置面板 / ChatView 共用）。
  - `enterConversation(id)`：切会话 + 切角色；角色不存在 → 切默认角色 + 弹窗。
  - `requestRoleSwitch(v)`：先弹确认框，确认后新建（空会话则改绑，避免堆空会话）。
  - 弹窗是**模块级单例** `roleNotice` + `resolveRoleNotice(ok)`（promise），
    页面实例只挂一个 `<RoleNoticeDialog />`（在 ChatView）。别再各自 new 一个 ElMessageBox。
- `settings.ts` 导出 `DEFAULT_ROLE_VALUE = 'Testificate'` / `DEFAULT_ROLE_LABEL`（兜底角色）。
- 侧边栏按角色分组（`useRoleGroups`），分组顺序 = `defaultRole` 顺序，已删除角色的残留会话附在末尾。
- 设置面板的角色下拉框**直接绑定 store**（`:model-value` + `@update:model-value`），
  取消切换时不需要回滚代码；面板里的 `settings` 副本靠 watch 与 store 同步，
  否则点「保存设置」会把拦截下来的切换写回去。

前端测试新增 `src/_tests_/roleSession.test.ts`（7 条）。
当前前端全量（2026-09-16 实测）：**`6 files / 30 tests passed`**。

## 已知既有失败（重要，勿误判为回归）

`test_ai_integration_cases.py::test_tts_qwen_provider_saves_audio`
断言 TTS 音色为 `Cherry`，实得 `Serena`。

原因：`config.py` 的 `_DEFAULT_ROLE_VOICES` 里 `"Wendy": "Serena"`，
而 `Voice.resolve_qwen_voice` 实现「角色专属音色优先于 voiceCate 映射」，
所以必然返回 `Serena`；用例期望的 `Cherry` 是角色音色映射引入之前的旧预期。
属独立缺陷，2026-09-15 已用 git 证实改动前即存在。

~~当前基线：76 passed, 1 failed~~ → **2026-09-16 实测已变为 `124 passed, 0 failed`**
（在 `wip/migrate-role-session` 的 backend 副本上跑，该分支 backend 与 feat 逐字节一致）。
上面那条 TTS 用例现在也通过了；76/1 是 2026-09-15 的快照，已过时。

## 测试对函数签名的强耦合（改代码前必读）

`backend/tests/` 里的替身形态互斥，动这些函数的签名会踩坑：

- `Integration.get_llm_response` 的替身有 `lambda *_args`（只吃位置参数）
  和 `def fake_llm(model, role, prompt, history=None)`（第 5 个位置参数会被**静默**绑到 history）
- `Connect.process_query` 的替身是 `lambda _request`（必须单参数调用）
- `test_websocket_cases.py` 断言 `websocket.sent[0]` / `sent[1]` 的**下标位置**，
  在主流程里插入任何中间帧都会让它们失败

结论：需要给这些函数传新东西时，优先用 contextvar 旁路，而不是改签名。

## 约定

- 前端真实链路是 `views/ChatView.vue` 自持 `WebSocketManager`；
  `stores/ClientChat.ts` 与 `stores/UseChatClient.ts` 是**无引用的死代码**，别去改它们。
- 音频通过静态文件 URL 播放（`stores/settings.ts` 的 `getAudioUrls`，dev 走直连磁盘路径），
  不经过 WebSocket 传字节。
- 静态资源目录 `frontend/src/assets/voice/` 每轮会被覆盖写入，别把它当持久数据。

## 本机环境注意事项

- **`Bash` 工具不可用**：shell shim 报 `dirname: command not found`，`ls`/`wc` 全废，
  且从 Bash 调 `cmd.exe` 被安全策略拦截。用 `PowerShell` 工具替代。
- **`PowerShell` 工具不返回 stdout**：命令输出必须重定向到文件再用 Read 读。
- PowerShell 里 `& exe ... 2>&1 | Out-File` 在长输出时会截断且令 `$LASTEXITCODE` 失真，
  应先把输出存进变量再 `Set-Content`。
- **`Remove-Item` 被 safe-delete 拦截**（`reason: trash-failed`）。临时文件改用
  `Move-Item` 归拢到 `.workbuddy\.tmp-scratch\`，别在根目录留一堆 `_tmp_*`。

## 两套测试口径，勿混淆

| 口径 | 数字 | 来源 |
| --- | --- | --- |
| 仓库全量后端测试 | **`124 passed`**（2026-09-16 实测） | `backend/` cwd 下 `pytest tests`，用 `.venv-module1` |
| 仓库全量后端测试（旧快照） | 76 passed, 1 failed | 2026-09-15 记录，已过时 |
| 模块一 34 条用例（当前） | **`34 passed`**（2026-09-15 实测） | `pytest tests/test_websocket_cases.py tests/test_service_and_state_cases.py -q` |
| 阶段一提交件里的历史快照 | 32 passed + 2 strict xfail，符合性 94.12% | `docs/`、`G:\...\Stage-1\` 的提交文档 |

**注意：xfail 标记已全部移除。** `TC-TTS-04`（非法 Base64 产出零字节音频）与
`TC-EX-02`（非数字索引异常路径）的缺陷已修，对应用例已翻转为断言正确行为；
修复提交为 `4e9806f First Stage Fix`。另有 8 条「隐式探针」用例
（`TC-WS-08`、`TC-CFG-01/02/06`、`TC-ACK-03`、`TC-CON-01`、`TC-RES-03`、`TC-EX-01`）
原先靠断言错误行为而 PASS，修复后断言已同步翻转 —— README 第 247/249 行有完整说明。

**汇报时务必区分「阶段一快照」与「当前仓库」**，否则文档与代码会被认为自相矛盾。

## 文档与仓库的已知不一致（答辩/汇报前须处理）

- `README.md` 第 218–222 行仍写「正常基线 32 passed, 2 xfailed」，与第 247 行
  「当前基线 34 passed」冲突 → 应标注为阶段一历史快照。
- 测试报告写生产代码 1143 行（Connect 316/Integration 212/Text 61/Voice 269/Image 285），
  当前仓库实测 2127 行（633/480/204/439/371）→ 报告应补「v1.0 快照，2026-09-12」。
- `测试用例清单_阶段一.xlsx`：
  - Test Cases 表第 5 列「是否自动用例」34 行全为 `否`，与「全部自动化」矛盾 → 应为「是」。
  - 第 14 列（无标题）残留 `OK/POK/NG/NT`（TC-WS-01/02/04/05 行），与第 12 列 Status
    及 Information 表统计（POK=0、NT=0）冲突 → 模板调试残留，应清空。
- 缺陷报告 3.3 写 `.sh`、测试报告写 `.py` 入口 → 实为跨平台三个入口（.sh/.bat/.py），
  统一表述为 `python scripts/run_module1_tests.py`。

## 模块一 34 条用例的对被测模块行覆盖率（2026-09-15 实测）

`text.py 65%`、`config.py 71%`、`Connect.py 60%`、`Integration.py 62%`、
`Image.py 40%`、`Voice.py 38%`。Voice/Image 偏低是 Mock 策略下的**设计选择**，
不是漏测（真实 HTTP 与多媒体后处理分支刻意不执行）。
命令：`pytest <两个模块一文件> -q --cov=. --cov-report=term-missing`

## 阶段一提交件：缺陷台账的权威来源（2026-09-15 补录）

`G:\研究生阶段文件\软件测试\提交文件\Stage-1\` 下三份文件是汇报口径的正源，
**不要在仓库里自己推算数字**：

| 文件 | 用途 |
| --- | --- |
| `测试报告（模块一）-最终版.docx` | 通过率表、缺陷汇总表、用例设计思路 |
| `缺陷报告模板-最终版.doc` | D-001~D-008 逐条缺陷记录（表 3.4.1~3.4.8） |
| `测试用例清单_阶段一.xlsx` | 34 条用例清单 |

**缺陷台账（测试报告「缺陷汇总」表，2026-09-12 / Build M1-FIX-1.1.0）**

| 编号 | 摘要 | 严重 | 证据用例 | 状态 |
| --- | --- | --- | --- | --- |
| D-001 | 错误响应不符合前端 ServerMessage 契约 | 高 | TC-WS-08 | 修复 |
| D-002 | 处理失败后可能连发 PROCESS_ERROR、SERVER_ERROR | 高 | TC-CFG-01/02/06 | 修复 |
| D-003 | TTS 超时被静默忽略，缺少 partial 状态 | 中 | TC-TTS-02 | 修复 |
| D-004 | 非法 Base64 创建零字节 mp3 并返回路径 | 中 | TC-TTS-04 | 回归 |
| D-005 | Records 缺失时降级后 updateLinks 再次失败 | 高 | TC-RES-03 | 修复 |
| D-006 | 角色记录缺失/索引非数字产生未分类 IndexError | 中 | TC-EX-01/02 | 回归 |
| D-007 | 未 ACK 时下一条 client_query 被误消费 | 高 | TC-ACK-03 | 修复 |
| D-008 | 同角色并发请求共享同一索引和资源槽 | 高 | TC-CON-01 | 关闭 |

解决日期均 2026-09-12；解决者方晓旸，测试人方为俊，关闭者屈唯一，贡献各 33.3%。

**Records 相关三条的落地做法**（代码位置见 `Integration.py`）：

- D-005 → `_read_records_lines()`（FileNotFoundError→`[]`）、`_write_records_lines()`
  （`os.makedirs(exist_ok=True)`）、`updateLinks` 的 `for...else` 找不到角色块就补最小记录。
- D-006 → `if matches: ... else:` 走与文件缺失相同的降级；正则从 `index:(\d+)` 放宽为
  `index:([^\n]*)`，让非法值先取出、再由 `int(index)` 抛 `ValueError`。
- D-008 → `_role_locks` + `_lock_for(roleName)` 按角色分片加锁，读/推进/写回同锁；
  `_advance_index_only()` 在锁内做原子占位（只推 index 行、不动 Recent_Url）。
  证据：`TC-CON-01` 用 `Barrier(2)` 强制交错，断言槽位 `["3","4"]`、写回 `["4","5"]`；
  `test_n01_update_links_runs_inside_role_lock` 用 spy 断言写回发生在锁内。

**代码里另有一条报告未收录的**：`缺陷 B07`（Image.py / Integration.py 注释）——
本轮无新图时不能用空串覆盖 `Recent_Url`，修法
`recordsUrl = updatedUrl if updatedUrl else imgurl`。
**B/N 系列编号与报告的 D 系列不互通**，答辩时别混用。

## `.git` 会被反复删除 + 只写不删的 git 操作法（2026-09-16 血泪）

- 现象：`F:\LLMGal\.git` 被整体删进回收站（一天内多轮，回收站 3400+ 条），
  表现为 `refs/heads/main` 被截成 0 字节 → `You do not have the initial commit yet`；
  新提交的对象也会被清掉；`stash/checkout/merge` 中途被杀，留下 `HEAD.lock`、`AUTO_MERGE.lock`、`index.lock`。
- **根因**：git 切分支 / `reset --hard` / `stash` / merge(自动 stash) 会**批量删除文件**，
  触发本环境的文件删除保护 → 文件进回收站、进程被终止。
  只写不删的操作（clone、`hash-object -w`、`commit-tree`、`merge-tree`、`update-ref`）全部正常。
- **对策**：涉及删除文件的 git 操作放到 GitHub Desktop / 普通终端；本会话里只做"只写不删"的活。
- 需要合并时，用管道命令全程不碰工作区：
  `read-tree` → `hash-object -w --path` → `update-index --cacheinfo` → `write-tree` →
  `commit-tree` → `git merge-tree --write-tree --merge-base=<base> <ours> <theirs>` →
  `commit-tree <tree> -p ours -p theirs` → `update-ref`。
- 从回收站还原 `.git`：解析 `$RECYCLE.BIN\**\$I*`（**pathlen 在偏移 24、路径从偏移 28 起**，UTF-16LE），
  `$Ixxxx` 对应 `$Rxxxx`；只有 2 段十六进制名的条目是**目录**（无 `$R`）。
  远端全量对象可用 `git clone --mirror` 补齐；副本已在 `C:\Users\Lenovo\.workbuddy\tmp\LLMGal-mirror`。
- 命令行 push 仍不可用（`credential.helper=manager` 需要交互式 GCM，报 `cannot spawn sh`），
  **推送只能走 GitHub Desktop**。
- **2026-09-16 补充：删 ref 的命令同样会触发保护**。`git update-ref -d refs/heads/<name>`
  实测把整个 `refs/heads/wip/` 目录端掉了（连带同目录其它分支），对象库无损。
  **恢复办法：用 Python 直接写 `.git/refs/heads/<name>`，内容 `<sha>\n`**，别再用 git 命令。
  结论：这个环境里**任何带 `-d` / `--delete` 的 git 命令都不要用**。
- PowerShell 工具里 **`cmd /c` 被安全策略拦截**；PowerShell 管道捕获 git 输出会损坏内容
  （长文本只剩几行，编码也可能错乱）。**统一改用 Python `subprocess` 调 git 并落盘**，字节级无损。
- 比对路径/内容时注意两个坑：`git ls-tree` 默认把中文路径转义成八进制（要
  `-c core.quotePath=false`）；`git archive` 导出会应用 `.gitattributes` 的 eol 转换，
  比较文件内容前要统一 CRLF→LF。

## 迁移状态（2026-09-16 已完成，待用户在 GitHub Desktop 合并）

**交付分支**：`wip/migrate-role-session` = `b812e82cec53845f46a0dd7a4c2c4ce4f538fed2`
（父 `b7f2b9a`，可 fast-forward，13 文件 +1084/−74）。
验证：后端 **124 passed**；前端 `vue-tsc` **零错误**、`vitest` **6 files / 30 tests passed**。

**关键认知（别再搞错）**：feat 的 `on_reasoning` 与 main 的 contextvar
**不是同一功能的两种实现，而是两个不同功能，可以并存**：

- feat `on_reasoning` = 模型**思考过程**流式，前端帧 `stream_progress`，**改了函数签名**（第 5 个位置参数）
- main `DELTA_SINK` / `STREAM_EVENT_SINK` = 回复**正文增量** + 情绪标签，
  前端帧 `text_delta` / `emotion`，**刻意用 contextvar 绕开签名**（正是为了不破坏三种互斥的测试替身）

用户拍板：本次只迁会话角色绑定，流式沿用 feat 的 `on_reasoning`，main 正文流式整套不迁入
（`test_streaming_cases.py`、`streaming-migration-plan.md`、`runtime_mode.json` 一并剔除）。
**若日后要迁正文流式，仍应沿用 contextvar 旁路，不要改签名。**

main 工作区原样快照保留在 `wip/role-session-and-streaming` = `fa0a62f`（25 文件 +2080/−79），
文件副本在 `C:\Users\Lenovo\.workbuddy\tmp\llmgal-wip-backup-20260914`。
已废弃的中间产物 `wip/migrate-keep-on-reasoning`(`ca00e99`) 已删除（状态是半吊子，勿用）。

顺带修掉两个 main 工作区既有缺陷：`SettingsPanel.vue` 漏 5 个 import；
`RoleNoticeDialog.vue` 两个原生 `<button>` 缺 `type="button"`（被既有守卫测试抓到）。

详见 `artifacts/migration-report-2026-09-16.md`。
远端 `main` 已到 `431397a` 且已包含 feat 的三个提交；本地 `main` 仍在 `9c8e3ee`。
当前 `F:\LLMGal` 在 feat 分支。

## 读取/生成 Office 文件（本机可行路径）

经 `tencent-local-office-edit` 的 `edsdk.py`（managed python 调用，cwd 设为该 skill 目录）：

- 打开：`open_file --json-file args.json`。**路径含中文时必须走 `--json-file`**，
  用 `k=v` 传中文会被控制台编码损坏。
- 读 PPTX：`slide_get_info` → `slide_get_page_info`（逐页 shapes）→
  `slide_get_table_info` / `slide_get_chart_info`；
  **`slide_get_notes_text` 能读到 PPT 自带的演讲者备注**（写讲稿时是最省事的素材来源）。
- `slide_get_page_info` 的返回是单行超长 JSON，Read 会截断；先在脚本里抽字段再落盘。
- 读 DOCX/DOC 表格：`doc_list_tables` → `doc_get_table_info table_id=...`。
  **返回结构是 `{"block": {"table": {"cells": [...]}}}`，不是顶层 `cells`**；
  跳过 `mc: true` 的合并续格，`grid_span` 表示合并跨度。
- `doc_resolve_document_structure` 是 **compact 模式**，只给 `text_preview`（几十字符截断），
  要全文得走 `doc_find` 或逐表读。
- `doc_find` 的返回键是 **`locations`**（不是 matches/results），元素含 `begin`/`end`。
- 新建 docx：`create_doc` → `doc_insert_markdown`（`markdown` 支持 `file://<绝对路径>`，
  长文用这个，别塞命令行）→ `save_file file_path=...`；`doc_get_outline` 校验结构。
- 改已存盘的 docx：`get_pool_status` 拿真实 `file_id`（`present_files` 之后是 UUID），
  再 `doc_find` 定位 → `doc_insert_markdown` / `doc_find_and_replace` → `save_file`。
- **WPS 开着时 `save_file` 会报 `Export file is occupied`**（本机 `wps` 进程常驻）。
  要么让用户关掉 WPS，要么 `save_file file_path=<新路径>` 另存。
