# LLMGal 项目长期约定

## 环境基座
- 后端解释器唯一可用 `E:\Anaconda\envs\vue-fastapi\python.exe`（3.11.13），备选 `py -3.11`。**没有 `python3.11`**；托管 `python3`（3.12/3.13）不可用 —— fastapi 0.95.1 + pydantic 1.10.7 导入即崩 `ForwardRef._evaluate() missing 'recursive_guard'`。
- 基线（2026-09-14 深夜）：后端 pytest **124 passed**、`scripts/run_module1_tests.sh` 34 passed、前端 vitest **23 passed**；`npm run build` 必须 EXIT 0（`vue-tsc -b` 的 `noUnusedLocals` 会让未用局部函数直接失败）。
- 启动：**必须在 `backend/` 下** `python.exe -m uvicorn Connect:app --host 127.0.0.1 --port 8000`。

## Windows 工具链
- 沙箱 Bash 缺 coreutils 且拦截 `wsl.exe` → **前端构建用 PowerShell**（不回显 stdout，需 `| Out-File -Encoding utf8 <log>` 再 Read）。完整 Git Bash：`"/c/Program Files/Git/bin/bash.exe" -c '...'`。原生程序传路径用 `F:/...`（`/f/...` 会拼成 `f:\f\...`），文本处理用 Python。
- POSIX 脚本要同时处理：解释器（`py -3.11`）、venv 布局（Win `Scripts/` vs POSIX `bin/`）、路径（`cygpath -m`）。

## 仓库卫生（硬规则）
- `backend/__pycache__/*.pyc` 有 7 个被 git 跟踪 → Python 执行一律带 `PYTHONDONTWRITEBYTECODE=1`。未经许可不做 `git commit` / `git push`。
- **项目改动已提交到分支 `feat/module1-mock-and-role-mgmt`（`a8c0983`，111 文件 / +11024 行）**。`main` 仍在 `37d2c2a`、落后 `origin/main` **5 个提交**，且 `main` 与 `testificate_fxy` 的 60 个差异文件里有 **27 个与工作区重叠** → 切分支必被 "local changes would be overwritten" 拒。**本机到 github.com 不通**（沙箱内 `SSL_ERROR_SYSCALL`、沙箱外代理 `CONNECT tunnel failed, response 502`）→ **命令行 push 不可用，推送只能靠老登在 GitHub Desktop 里点**。老登用 **GitHub Desktop**，它切分支时会**自动 stash**（命名 `!!GitHub_Desktop<分支名>`，并带 `-u`，连 `artifacts/`、`tests_ai/`、新建角色文件等未跟踪内容一起收走），工作区会瞬间"清空"到旧状态。**看到文件行数莫名变少 / mtime 齐刷刷同一秒，先查 `git reflog --date=local` 和 `git stash list`，再去 `git show 'stash@{0}:<path>'` 核对内容，别急着重写代码。**
- **GitHub Desktop 报「先 commit 或 stash 才能切分支」的真凶往往是索引里的未合并条目**（`UU` / `git ls-files -u` 有输出，常见于 `backend/__pycache__/*.pyc`），不是普通脏工作区。解法：`git checkout HEAD -- <每个冲突路径>` → `git reset` → `git checkout <目标分支>` → `git stash apply 'stash@{0}'`（**用 apply 不用 pop**，失败可重来）。
- **stash 恢复后不要拿备份覆盖同路径文件**：两份内容常是互补的（stash 版是切分支前的累积，备份版是切分支后新写的），直接覆盖会静默丢掉大段内容。**先 `git show 'stash@{0}:<path>'` 对比，再决定合并方向**。
- **禁止在 Python 里删文件**：safe-delete 守卫把 `os.remove` 改成移入回收站，累计超 50 → `SAFE_DELETE_BULK_CONFIRM_REQUIRED` / `SystemExit(1)`，`except OSError` 接不住，直接打崩整条 WebSocket 请求。覆盖写入不受影响 —— 更新内容一律覆盖。
- **同一文件在一次工具调用块里发两个 Edit，后写的覆盖先写的** → 改同一文件多处必须串行。

## 前后端契约陷阱
- 禁止本地部署，一律云端 API；当前零多轮记忆，别买长窗口。
- `modelText` 优先级高于 `.env` 且存 localStorage；厂商不认识的 ID 直接 1211 整轮失败 → `config.resolve_text_model()` 白名单收敛。
- 心跳回 `pong` 不是 `heartbeat`：加类型过滤必须同步 `MessageType.ts` 的 `ServerMessageType`。
- 错误报文必须带 `type/message_id/status/payload` 四项（`isServerMessage` 校验，`status` ∈ `success|partial|error`），否则被丢弃、用户看不到提示。`ChatView.vue::handleServerMessage` 的 `isErrorResponse` 分支已会清 isLoading、`Stop`→`Send`、把空白消息换成 `请求失败：{payload.message|detail|code}`。
- **`<el-form>` 渲染的就是原生 `<form>`**（Element Plus `es/components/form/src/form2.mjs` → `createElementBlock("form", ...)`），所以**放进 el-form 的原生 `<button>` 必须显式写 `type="button"`** —— 缺省 `type` 是 `submit`，点一下表单提交、整页刷新且不报任何错。`el-button` 因为 `nativeType` 默认 `'button'` 才安全。全项目模板守卫：`frontend/src/_tests_/roleReconcile.test.ts` 递归扫 `src/**/*.vue`，任何原生 `<button>` 缺 `type` 即失败。
- 发声统一走 `utils/audioBus.ts`（先 `claimPlayback` 抢占再播，`isPlaybackOwner` 供自愈看门狗让位）。
- **`<audio>` 五条铁律**：① 元素常驻不重建，`src` 只在一处命令式设；② `src` 带时间戳 → `load()` → 轮询等 `readyState>=2` 再 `play()`；③ 过期请求**静默 return，绝不 `pause()` 共用元素**（特征 `paused=true readyState=4 currentTime=0 error=无`）；④ `stopAudio()` 先 `playToken++` 并清全部定时器；⑤ 不依赖 `canplay`/`loadedmetadata`，靠轮询。配套 `watchPlaybackHealth` + `installPauseProbe`；回归 `frontend/src/_tests_/chatAudio.test.ts`。
- `blob:` URL 不能拼查询串（`?_t=` 只对 http(s) 有效，blob 拼串 → `readyState` 永远 0、无 error、静默超时）。
- 两套音色 ID 不能混：`VOLC_TO_QWEN_VOICE` 的 key 是火山 ID，`QWEN_VOICE_CATALOG` 的 key 是 Qwen 音色名。`Voice.resolve_qwen_voice` **直接指定 Qwen 音色名的场景必须走第一级**，否则静默回落 `TTS_QWEN_DEFAULT_VOICE`。验证音色用同一段文字 + 不同音色对照。

## 图片生成风格（2026-09-14 实测，别再改回 SD 脚手架）
- **画风单一入口 `Image.build_style_head(style="")`**：显式 `style` > `config.IMAGE_STYLE_PROMPT` > 内置 `ANIME_STYLE_HEAD`（默认**二次元动漫原画**）。任何出图提示词都必须从这里取，禁止各处手写（历史 bug 来源）。`build_portrait_prompt` / `build_expression_prompt` 两条路径都走它。
- **禁止 SD 标签脚手架**（`Positive Prompt:` / `[Photography: ...]` / `masterpiece`）：`IMAGE_PROVIDER=zhipu`（CogView-3-Flash）是指令式模型，摄影词汇会把画面强推向写实人像。实测：含 `[Photography]` → 写实照片；删该行 → 半写实插画；风格前置自然语言 → 2D 动漫立绘。
- 回归闸门 `backend/tests/test_image_style_cases.py`（TC-STYLE-01..13），查禁用词前先剥掉 `PORTRAIT_NEGATIVE_HINT`。前端无画风输入项，`style` 恒空 → 永远默认二次元；非空是**整体替换**。
- CogView 只有文生图、无 seed → 同 prompt 两次出图角色长相不同，只能证明"风格一致"；要身份一致须切 `volcengine` 图生图。

## 静态资源槽位（构建期快照陷阱）
- `settings.ts` 的 `import.meta.glob` 是**构建期快照**：dev 下 `/src/assets/...` 直连路径**必须排候选第一**（`getAudioUrls()` + 按 `error` 依次回退），否则回退到同名历史 mp3，声音与文字对不上。
- 图片同理：`getImageUrls()` 三级候选 —— 构建期 glob → dev 直连 `/src/assets/pictures/{name}/{name}_{idx}.jpg` → `staticUrl('/static/pictures/...')`，**第三级 dev/prod 都必需**（运行时创建的角色进不了生产构建）。配套 `useRoleImage(...)` 接 `<img @error>` 逐个试；坑：候选含恒非空的 `/static`，"空串"只能靠走完列表；ChatInput 的 `i` 必须声明在 `useRoleImage` 之前（`watch immediate` 的 TDZ）。
- 后端每轮覆盖 `frontend/src/assets/voice/{role}/{role}_{index}_Stream.wav`（index 0-9），播放必须带时间戳破缓存。
- dev 下 Vite 不监视 `src/assets/voice`、`pictures`、`roles`（`server.watch.ignored`），否则后端写文件触发整页重载；代价是手工新增文件需重启 dev。三处都要挡 —— `roles/*.txt` 同样被 `import.meta.glob(eager)` 静态引用，删除角色会删掉它并触发整页重载（把成功提示刷掉）。`/static` 挂 `frontend/src/assets`；`VITE_API_BASE` **必须写全 `http://127.0.0.1:8000`**。`backend/smoke_e2e.py` 会真实调 LLM+TTS 并覆盖语音槽位，别一边冒烟一边试聊。

## 环境可复现性（`docs/module1/LLMGal_环境可复现性分析报告.md`）
- `pycryptodome` 钉 `3.21.0`（cp37-abi3 轮），`volcengine` 由 `scripts/setup_env.sh` 以 `--no-deps` 装。查 wheel 可用性别用 `"cp311" in filename` 过滤（漏判 abi3）。venv 不可重定位，只能目标机重建。
- **未声明依赖**：`httpx==0.28.1` 由 `openai==1.93.2` 间接引入，`requirements.txt` 里没有；本机 venv 实测 `socksio` / `PySocks` **均 MISSING**。运行环境若设 `ALL_PROXY=socks5://...`，openai SDK 的 httpx（`trust_env` 默认 True）会报 "Using SOCKS proxy, but the 'socksio' package is not installed"；`requests` 侧（Image/Voice）走 SOCKS 需要的是 `PySocks`。
- **待修勿忘**：`image_emotions.py` / `TestSubject2.py` / `tts_websocket_demo.py` 硬编码火山密钥且已入库；**`backend/.env` 已被 git 跟踪且已提交**（commit `37d2c2a`，含全部 API Key）→ 需 `git rm --cached backend/.env` **并轮换全部密钥**。

## 模块一 mock 测试
- 范围：`backend/tests/` + `frontend/src/_tests_/example.test.ts`，全 Mock/Stub，`conftest.py` autouse fixture 把漏掉的真实 HTTP/WS 调用判失败。
- `@pytest.mark.xfail(strict=True)` 用例一旦通过变 XPASS 判 FAILED → 修好缺陷必须同步删标记。
- 8 条用例以"断言缺陷行为"通过（`TC-WS-08`/`TC-CFG-01,02,06`/`TC-ACK-03`/`TC-CON-01`/`TC-RES-03`/`TC-EX-01`），**通过=缺陷仍在**，修源码要同轮翻转断言。冻结：`Text.py` / `Image.py` 真实调用（`TC-LLM-01`/`TC-IMG-01`）属后续单独指示范围。

## 角色创建 / 删除
- REST 全在 `Connect.py`（`def` 走线程池）：`GET /api/voices/preview`、`POST /api/roles/generate-image|create|delete`、`GET /api/roles/temp-images|status`；核心 `backend/Create_New_Role.py`。
- 落盘：`roles/<角色>.txt`、`pictures/Role_Description/<角色>.txt`（Subject/Appearance 两行）、`pictures/<角色>/` 下 `_original.jpg` + 7 张情绪图、`pictures/temp/`、`voice/_samples/<音色>.wav`。角色→音色存 `backend/custom_role_voices.json`（`config.resolve_role_voice` 第三级查它）。
- 音色样本 27 个（`QWEN_VOICE_CATALOG` 全量）；重跑 `python Create_New_Role.py samples --force`（**cwd 必须 `backend/`**）。`Stella` 只支持 instruct、方言音色只支持 realtime，**都不能用于 `qwen3-tts-flash`**。异步创建：`creatingRoles` + `utils/roleCreation.ts`（**全局单例**，ChatView 挂载 `reconcileCreatingRoles()` 自愈）。
- 删除：`POST /api/roles/delete` body `{roleName}` → `Create_New_Role.delete_role()`，清 `pictures/<角色>/`、`Role_Description`、`temp/<角色>_*.jpg`、`roles/<角色>.txt`、`voice/<角色>/`、`voice/_mock/<角色>/`、`Records.txt` 整段、`custom_role_voices.json` 登记、`ROLE_CREATION_STATUS`（不存在的记进回执 `missing`，不算失败）。
- **三条硬约束**（`test_role_delete_cases.py` TC-DEL-01..12）：① 内置角色 403（`BUILTIN_ROLES` 由 `_DEFAULT_ROLE_VOICES` 派生，**不看 `.env`**）；② `safe_role_name` 挡路径穿越（拒空/`.`/`..`/`/`/`\`/`:`/下划线开头，后者会与 `_samples`/`_mock` 撞名）；③ 不碰别的角色（`Records.txt` **整段摘除**，留空壳下次启动仍会被当成该角色存在）。status=creating → 409。
- 前端 `settings.ts::purgeRole()` 清 `customRoles`+`customRoleDetails`+`creatingRoles`，删当前角色时回退 `defaultRole[0]`；**顺序不能反**：先等后端 200 再清前端。
- **角色列表的真相源在后端磁盘，前端 `customRoles`（localStorage key `ai-chat-settings`）只是缓存**。`useRoleOptions()` = `defaultRole + customRoles`。删除流程被打断（页面刷新、关页、别的标签页删过、手工清过 assets）时 `purgeRole` 不会执行，缓存里就留下磁盘上已不存在的**幽灵角色** —— 表现是「明明删了，下拉框里还在，再点删除又像是没反应」。
- 对账机制：`Create_New_Role.list_custom_roles()` **六路探针取并集**（`custom_role_voices.json` 键 / `roles/*.txt` / `Role_Description/*.txt` / `pictures/<角色>/` / `pictures/temp/<角色>_<idx>.jpg` / `voice/<角色>/` + `voice/_mock/<角色>/`），减去 `BUILTIN_ROLES` 与内部目录；REST `GET /api/roles/list`（出错 502）。前端 `utils/roleCreation.ts::reconcileCustomRoles()` 在 `ChatView` 挂载时跑，**请求失败/结构不对就一个都不动，「创建中」的跳过**。删接口的清理范围与探针范围必须同步改，否则出现「删了清单还在」的静默假象（`test_role_list_cases.py` TC-LIST-01..11 钉对称性）。已知限制：`IMAGE_PROVIDER=zhipu`（CogView）只有文生图，7 张情绪图无表情迁移。

## 运行时模式 Mock / 正式版（2026-09-14）
- `config.get_mode()/is_mock()/set_mode()`，落盘 `backend/runtime_mode.json`（**不存在 = 正式版**，已 gitignore）；REST `GET/POST /api/system/mode`、`/health/config` 带 mode。`get_mode()` **每次读盘、无进程内缓存**（缓存会让多 worker / 手工编辑时界面与后端各说各话），落盘 tmp + `os.replace`。
- **Mock 拦截点只有一处**：`Integration.Response_Collection` 第一行 `if config.is_mock()`。`MockMode.py` **不 import 任何厂商调用函数**，5 元组契约与正式版一致 → 前端零改动。固定 `emotion='neutral'`、`index='0'`（不推进 Records）、`imageUrl=''`。
- 音频"固定" = 把本地样本（`voice/{role}/{role}_test_Stream.wav` → `_test.*` → `_samples/{音色}.wav`，只读）**复制**到隔离目录 `voice/_mock/{role}/{role}_0_Stream.{ext}`，**绝不现场合成**；无源 → `status='partial'` 且不建目录。
- **音频目录由「这条消息自带的 mode」决定**（`payload.mode` → `getAudioUrls(role, index, mode)`），**禁止用 `settings.appMode` 选目录**，mock 时不回退正式版目录。Mock 下 AI REST 直接 409（`generate-image`/`create`/缺样本的 `voices/preview`）。
- 测试 `test_mode_switch_cases.py`（TC-MODE-01..14）；`conftest.py` autouse fixture 把模式钉死 prod。前端设置页 `.app-mode-bar`（**样式必须定义在 `.create-role-btn` 之后**，否则 width 被它的 80% 覆盖）+ ChatView 头部 MOCK 徽标；`settingsStore.appMode` 只是显示镜像，真相源在后端。
- 端到端验证：uvicorn 起 8123 → 切模式 → 发一轮 `client_query` → 断言 emotion=neutral/index=0/imageUrl=''。收尾 `rm backend/runtime_mode.json`。
