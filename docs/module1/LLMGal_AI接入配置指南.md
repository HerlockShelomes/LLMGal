# LLMGal AI 接入配置指南（填什么、填在哪）

| 项目 | LLMGal（Vue3 + FastAPI 对话式 Galgame） |
|---|---|
| 适用版本 | 本轮「前后端连通 + AI 接入」改造之后（backend 63 测试通过 / 覆盖率 72%） |
| 编制日期 | 2026-09-13 |
| 配套文档 | 《LLMGal_大模型实惠档选型（测试期）.md》（为什么选这几家）、《LLMGal_现存缺陷与修复流程清单.md》（缺陷明细） |

> 一句话：**所有密钥只填一个地方——`backend/.env`；前端只填 `frontend/.env.local` 两个地址变量。**
> 代码里已经没有任何硬编码密钥。

---

## 一、最快上手（3 步）

```bash
# 1. 后端：复制配置模板并填密钥
cd backend
cp .env.example .env          # Windows: copy .env.example .env

# 2. 前端：复制配置模板（只填地址，不填密钥）
cd ../frontend
cp .env.example .env.local    # Windows: copy .env.example .env.local

# 3. 启动（后端必须在 backend 目录下启动，静态资源用的是相对路径）
cd ../backend
python -m uvicorn Connect:app --host 127.0.0.1 --port 8000
```

浏览器打开前端后，先访问一次自检接口确认配置是否被读到：

```
http://127.0.0.1:8000/health/config
```

它会告诉你当前用的哪家模型、还缺哪些密钥（**不会返回密钥内容**）。缺什么它会列出来，照着补即可。

---

## 一之二、开发模式本机启动与试聊（照着做即可）

### 0. 前置确认

```bash
curl http://127.0.0.1:8000/health/config    # 服务没起时先跳过
```

配置齐全时 `missing` 为 `[]`。素材方面，四个角色（Testificate / Wendy / Testificate_Boy / GirlProgrammer）的人设、七张情绪立绘、语音目录**都已齐备**，首轮聊天不会触发补图。

### 1. 开两个终端（顺序别反：先后端，再前端）

**终端 A —— 后端**（必须在 `backend/` 目录下启动，静态资源用的是相对路径）

```bash
cd F:/LLMGal/backend
E:/Anaconda/envs/vue-fastapi/python.exe -m uvicorn Connect:app --host 127.0.0.1 --port 8000
```

看到下面这段就说明起来了，同时会打印自检与告警：

```
[LLMGal] 当前配置：
文本模型 : provider=zhipu model=glm-5.3-flash ...
语音合成 : provider=qwen model=qwen3-tts-flash voice=Serena
图像生成 : provider=zhipu model=cogview-3-flash
```

**终端 B —— 前端**

```bash
cd F:/LLMGal/frontend
npm run dev
```

```
VITE v6.3.5  ready in 1206 ms
➜  Local:   http://localhost:5173/
```

> **为什么必须先起后端**：前端有断线重连，但采用指数退避且**最多 5 次**，超限后不再重试。若先开前端，等后端起来时重连次数可能已用尽，需要刷新页面才能恢复。

### 2. 浏览器打开与试聊

1. 访问 **http://localhost:5173/**
2. 打开**设置面板 → 「角色选择」下拉**，挑一个角色（`Testificate` 为默认，`Wendy` 已实测跑通）
3. 在输入框发一句话，例如「你好，今天过得怎么样？」

**正常现象**：

- 助手回复带角色口吻，且开头有 `(高兴)` 之类的情绪标签 —— **这是模型原文，前端展示时已剥离**，你看到的正文是干净的
- 立绘按 `emotion` 自动切换到对应静态图（neutral / happy / sad / fear / angry / surprised / shy）
- 语音自动生成并播放，文件落在 `frontend/src/assets/voice/<角色>/<角色>_<序号>_Stream.wav`
- 左下/顶部若弹出「回复已生成，但语音或图片生成失败」，对应后端 `status: partial`，文本仍正常

### 3. 确认真的走通了

- 后端终端会打印 `connection open`、角色情绪、`是否进行实时图片生成: False`
- 浏览器 F12 → Network → WS，能看到 `client_query` 与 `assistant_response` 两帧，`status` 为 `success`
- 想不打开前端就验证：`cd backend && python smoke_e2e.py ws://127.0.0.1:8000/ws/chat`

### 4. 常见状况

| 现象 | 原因 / 处理 |
|---|---|
| 语音没声音 | 浏览器自动播放策略会拦截，点一下页面任意处再试（代码已 catch，不会报错） |
| 一直连不上 | 后端没起，或重连次数用尽 → 起后端后**刷新页面** |
| 回复很慢（>10s） | 模型首次调用含建连开销；后续约 3–7s。想更快/更省可确认 `TEXT_REASONING_EFFORT=low` |
| 想让语音带情绪 | `.env` 里 `TTS_QWEN_USE_INSTRUCTIONS=1`，重启后端 |

### 5. 关于实时出图（默认关闭）

`ChatView.vue` 里 `realTimeRendering` 目前**固定为 `false`**，即只用已有静态立绘——**不调用图像接口、不花钱**，适合测试期。要试实时生成需改该值，届时每轮会调图像接口（免费档 CogView 不花钱，但更慢）。

### 6. 停止

两个终端各按 `Ctrl + C`。

---

## 一之补、实测校准（2026-09-13 用真实密钥跑通后修正）

初版文档里有三处来自资料推断、但**真机验证不成立**的地方，已修正，请以本节为准：

| 项 | 初版写法（错） | 实测结论（对） |
|---|---|---|
| 智谱模型 ID | `glm-4.7-flash`（永久免费） | 该 ID **不存在**，会报 1211「模型不存在」。账号实际可用：`glm-4.5 / 4.5-air / 4.6 / 4.7 / 5 / 5-turbo / 5.1 / 5.2 / 5.3 / 5.3-flash`。默认已改为 **`glm-5.3-flash`** |
| 思考开销 | 未考虑 | flash 档是推理模型，思考也计费。加 `reasoning_effort=low` 后：66 tokens/2.7s → **20 tokens/0.7s**，省约 3 倍 |
| 语音接口 | 以为走 OpenAI 的 `/compatible-mode/v1/audio/speech` | 该端点 **404**。正确端点是 `/api/v1/services/aigc/multimodal-generation/generation`；且非流式响应里 `data` 为空、音频在 `output.audio.url`；返回的是 **WAV 不是 MP3** |

**因此**：默认配置已能直接跑通，无需你手动改模型。想更强角色一致性可把 `TEXT_REASONING_EFFORT` 改成 `high`（成本约 3 倍）；想让语音带情绪可把 `TTS_QWEN_USE_INSTRUCTIONS` 改成 `1`。

---

## 二、必填项清单（backend/.env）

### 最小可用组合（免费档，推荐先跑这个）

| 字段 | 填什么 | 去哪拿 | 不填会怎样 |
|---|---|---|---|
| `ZHIPU_API_KEY` | 智谱 API Key | https://open.bigmodel.cn → 控制台右上角 API Keys（手机号注册、免信用卡） | 文本对话与图像都不可用，请求返回 401 |

**只填这一个 Key，文本（GLM-4.7-Flash，永久免费）和图像（CogView-3-Flash，免费）就都能跑了。**

### 语音（强烈建议也填，否则每轮没有声音）

| 字段 | 填什么 | 去哪拿 | 说明 |
|---|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里百炼 API Key | https://bailian.console.aliyun.com（支付宝登录、免信用卡） | Qwen3-TTS **每月 100 万字符免费**，够约 1 万轮对话 |

> 注：本机环境变量里已经存在 `DASHSCOPE_API_KEY`，若你想改用另一个账号，在 `.env` 里显式覆盖即可（`.env` 会写入 `os.environ`，但已有同名环境变量优先——需要覆盖时请先在系统中 unset 或直接改系统变量）。

### 可选：换成别家文本模型

| 想用的模型 | 改哪个字段 | 还要填什么 |
|---|---|---|
| 智谱 GLM-4.7-Flash（默认，免费） | `TEXT_PROVIDER=zhipu` | `ZHIPU_API_KEY` |
| DeepSeek（付费兜底最低价档） | `TEXT_PROVIDER=deepseek` | `DEEPSEEK_API_KEY`（platform.deepseek.com） |
| 阿里通义（每月免费额度） | `TEXT_PROVIDER=qwen` | `DASHSCOPE_API_KEY` |
| 任意 OpenAI 兼容端点 | `TEXT_PROVIDER=custom` | `TEXT_BASE_URL` + `TEXT_MODEL` + `TEXT_API_KEY` |

### 可选：图像换成更高质量的付费模型

| 字段 | 说明 |
|---|---|
| `IMAGE_PROVIDER=zhipu`（默认） | CogView-3-Flash，免费出图，适合跑通流程 |
| `IMAGE_PROVIDER=seedream` | 火山 Seedream，质量更好，**按张计费（约 0.20 元/张）**，需要 `ARK_API_KEY` |
| `IMAGE_PROVIDER=volcengine` | 火山视觉智能，需要 `IMAGE_VOLC_ACCESS_KEY` / `IMAGE_VOLC_SECRET_KEY`，且要装 `volcengine` SDK |

> 提醒：在缺陷 B07/B05 修好之前不要上付费图像模型——现在已修好（缺几张补几张、不再整套重生成），可以按需切换。

### 可选：语音换成火山豆包（音质更好，但按字数计费）

```
TTS_PROVIDER=volcengine
TTS_VOLC_APPID=你的 AppID
TTS_VOLC_TOKEN=你的 Access Token
```

### 安全项（建议填）

| 字段 | 说明 |
|---|---|
| `WS_AUTH_TOKEN` | WebSocket 鉴权令牌。留空＝开发模式（启动会告警），**任何能访问端口的人都能消耗你的额度**；填写后前端必须带同名 token |
| `CORS_ALLOW_ORIGINS` | 跨域白名单，生产请改成前端实际域名，不要留 `*` |
| `HOST` | 默认 `127.0.0.1`（只监听本机）。要局域网访问才改 `0.0.0.0`，**并且必须同时配 `WS_AUTH_TOKEN`** |

---

## 三、前端要填的（frontend/.env.local）

| 字段 | 默认值 | 什么时候要改 |
|---|---|---|
| `VITE_WS_URL` | `ws://localhost:8000/ws/chat` | 后端换了端口或部署到别的机器 |
| `VITE_WS_TOKEN` | 空 | **必须与后端 `.env` 里的 `WS_AUTH_TOKEN` 完全一致**；后端没开鉴权就留空 |

---

## 四、验证是否接成功

### 1. 服务自检

```
GET http://127.0.0.1:8000/health/config
```

`missing` 数组为空即表示配置齐全。

### 2. 端到端冒烟（真实进程 + 真实 WebSocket）

```bash
cd backend
python smoke_e2e.py ws://127.0.0.1:8000/ws/chat
```

它会依次验证：心跳 → pong、非法 payload → `invalid_message`、合法查询 → 有明确响应。
填好密钥后，第三项应返回 `assistant_response` 且 `status` 为 `success`。

### 3. 回归测试

```bash
./scripts/run_module1_tests.sh     # 后端，当前基线 63 passed
cd frontend && npx vitest run      # 前端，1 passed
```

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 返回 `PROCESS_ERROR`，detail 里有 401 | 密钥没填或填错 | 检查 `.env` 对应字段，重启服务（`.env` 只在启动时读一次） |
| `FileNotFoundError: 角色人设文件缺失` | `frontend/src/assets/roles/<角色>.txt` 不存在 | 这是本轮新增的明确报错（原缺陷 N03），建好文件即可 |
| 服务启动后前端连不上 | 后端默认只监听 `127.0.0.1` | 同机访问用 `127.0.0.1`；跨机改 `HOST` 并配 `WS_AUTH_TOKEN` |
| 前端报 `AUTH_403` | 后端开了鉴权但前端没带 token | 确认两端 token 完全一致（区分大小写、无多余空格） |
| 对话没有记忆 | 前端没发 `history` | 本轮已修复；检查前端版本是否包含 `buildHistory`，后端 `/health/config` 正常不代表前端已更新 |
| 每轮都重新生成图片、费用飞涨 | `Recent_Url` 被清空 | 本轮已修（缺陷 B07）；若仍出现请检查 `Records.txt` 是否被手动改动 |
| 听到的语音里念出「（高兴）」 | 情绪括号没剥离 | 本轮已修（缺陷 N04）；确认后端 `Voice.strip_emotion_tags` 生效 |
| 页面每隔一段时间弹「请求被后端拒绝：未知原因」 | 后端心跳回的是 `pong`，前端没识别就被当成非法报文 | 已修（`WebSocketManager.ts` 对 `pong` 直接返回）。旧版本请刷新页面 / 重新构建 |
| 返回 `模型不存在` (1211) | 模型 ID 在账号下不可用 | 见下方「模型名收敛」；可用清单见「一之补」节 |
| 设置面板里选的模型不生效 | 该 ID 不在当前 provider 白名单内，被回落成 `.env` 的 `TEXT_MODEL` | 后端日志会打一行 WARNING；确认可用后把它写进 `TEXT_MODEL_ALLOWLIST` |
| 语音没生成、`status` 是 `partial` | 语音接口 404 或返回体没有 url | 确认用的是官方 `multimodal-generation` 端点；`partial` 表示文本成功但语音/图片失败 |
| 新语音播放不了 | 扩展名与格式不符 | Qwen3-TTS 产出 WAV，文件为 `*_Stream.wav`；前端已改为 wav 优先、mp3 回退 |
| 控制台显示 `play() 已被接受` 但没声音 | 同元素上的过期 `play().then()` 补刀 `pause()` | 已修；日志若再出现 `paused=true readyState=4 currentTime=0`，看 `[音频] 播放被中断` / `音频被外部 pause()` 的调用栈（见第八节铁律 3） |
| 点「停止」后过一两秒声音又自己响了 | `stopAudio()` 没有作废在途的兜底定时器 | 已修；`stopAudio()` 现在会 `playToken++` 并清空全部定时器（第八节铁律 4） |
| 听到的语音和屏幕上的文字对不上 | dev 下 `import.meta.glob` 拿到了上一轮的历史 mp3 | 已修；`getAudioUrls` 在 dev 下优先直连磁盘上的最新 wav（见第八节） |
| 语音刚响一声就被掐掉、控制台日志被清空 | 后端每轮往 `src/assets/voice/` 写新文件，Vite 监视到变更后触发 HMR / 整页重载 | 已修；`vite.config.ts` 的 `server.watch.ignored` 排除了 `src/assets/voice` 与 `pictures` |

---

## 六、本轮改造对应的代码位置（便于排查）

| 关注点 | 文件 | 说明 |
|---|---|---|
| 密钥 / 模型 / 端点 | `backend/config.py` | 新增，唯一的配置来源 |
| 配置模板 | `backend/.env.example` | 新增，复制为 `.env` |
| 文本模型 | `backend/Text.py` | 人设改 `system`、支持多轮、密钥走配置 |
| 语音 | `backend/Voice.py` | 新增 Qwen3-TTS 免费档；剥情绪括号 |
| 图像 | `backend/Image.py` | 新增 CogView 免费档；只补缺失图片 |
| 编排 | `backend/Integration.py` | 并发写回加锁、状态降级、保留 Recent_Url |
| WebSocket 契约 | `backend/Connect.py` | 鉴权、心跳、取消、`invalid_message`、线程池 |
| 前端连接 | `frontend/src/utils/WebSocketManager.ts` | 监听解绑、心跳、事件分发 |
| 前端多轮 | `frontend/src/views/ChatView.vue` | `buildHistory()`，发送完整上下文 |

---

## 七、模型名的收敛规则（重要，1211 的根因）

前端设置面板里选的 `modelText` 会原样传到后端并发给厂商。旧版默认值是
`deepseek-ai/DeepSeek-V3`——那是旧中转站的命名，在智谱账号下并不存在，
请求直接 1211「模型不存在」，整轮对话失败。

现在的规则见 `backend/config.py::resolve_text_model`：

1. 选「跟随后端配置（推荐）」或模型名为空 → 用 `.env` 里的 `TEXT_MODEL`。
2. 模型名在当前 provider 的白名单内（智谱的 `glm-*` 真实 ID）→ 原样使用。
3. `TEXT_PROVIDER=custom` → 原样放行（端点你自己指定，后端无从预知可用模型）。
4. 其余一律回落 `TEXT_MODEL`，并在后端日志打一行 WARNING，**不让请求失败**。

要让白名单外的模型可用，在 `backend/.env` 加一行（改完要重启后端）：

```ini
TEXT_MODEL_ALLOWLIST=你的模型ID,另一个模型ID
```

**老用户注意**：模型选项存在浏览器 localStorage 里，旧值不会被自动改写。
现在找不到匹配项时会回落到空串（即跟随后端配置），所以不会报错；
但设置面板下拉框可能仍显示旧条目，进去选一次「跟随后端配置（推荐）」即可。

---

## 八、语音播放的四条铁律（改 `ChatView.vue` 音频前必读）

这一块连续踩了三次坑，每次现象都不一样、看起来都像"浏览器的问题"，实际全是自己写出来的。
四条规则各自对应一次事故：

**铁律 1：音频元素必须常驻，`src` 只在一处命令式设置。**
曾经同时存在 `watch(currentAudioUrl) → pause()+load()`、`:key` 重建 `<audio>`、
`@canplay` 自动 `play()` 三套机制，结果两段语音重叠。
`load()` 会**重新触发** `canplay`，把刚 `pause()` 的元素又复活；
而浏览器对「已移出文档的 media element」的 `pause` 是**异步**的，
`:`key` 换掉元素的那一瞬间，旧元素往往还在发声。

**铁律 2：`set src → load() → 等 readyState ≥ 2 → play()`，四步顺序不能变。**
- 只 `set src` 不 `load()`：部分浏览器推迟加载，`readyState` 永远停在 0 → 没声音；
- `load()` 后**立刻** `play()`：`load()` 把 `readyState` 打回 `HAVE_NOTHING`，
  此时 `play()` 的 promise 会被挂住很久，落定时早已是"过期请求"；
- 只在 `readyState ≥ 2`（`HAVE_CURRENT_DATA`）之后才 `play()`，这一条最关键。

**铁律 3：过期请求一律静默忽略，绝不 `pause()` 共用的元素。**
这是"日志说 `play() 已被接受`，但就是没声音"的真正原因。原来的写法是：

```js
el.play().then(() => {
  if (token !== playToken) el.pause()   // ← 致命：这是同一个 <audio>
})
```

新一轮已经让**同一个元素**改播新音频了，旧 promise 迟到落定后这一刀 `pause()`，
掐掉的正是刚开始播的新语音。典型日志特征：

```
[音频] play() 已被接受
[音频] 复查: paused=true readyState=4 networkState=1 currentTime=0 error=无
```

`readyState=4`、`error=无` 却 `paused=true` 且 `currentTime=0` = **有人调了 pause()**，
不是加载问题、也不是自动播放被拦截。过期就 `return`，什么都别做。

**铁律 4：`stopAudio()` 必须递增播放令牌。**
只 `pause()` 不清令牌的话，点「停止」之后旧的轮询/自愈定时器仍认为自己是当前请求，
会把声音**复活**。现在 `stopAudio()` 第一件事就是 `playToken++` 并清空全部定时器。

### 配套的两道保险

| 机制 | 位置 | 作用 |
|---|---|---|
| 播放自愈 | `ChatView.vue::watchPlaybackHealth` | `play()` 被接受后每秒复查，若 `paused && currentTime===0` 就重播，最多 4 次 |
| 暂停探针 | `ChatView.vue::installPauseProbe` | 元素被**外部** `pause()` 时打出调用栈（自己 `stopAudio` 触发的不报），用于下次定位真凶 |
| 候选地址回退 | `settings.ts::getAudioUrls` | dev 下优先磁盘上的最新 wav，404 时自动回退到构建期快照里的历史 mp3 |

### dev 下为什么必须优先"直连磁盘路径"

后端每轮**覆盖写** `frontend/src/assets/voice/{角色}/{角色}_{序号}_Stream.wav`，
而 `import.meta.glob` 是**构建期快照**：收不到这一轮新写的文件。
旧逻辑"先查快照、查不到再回退"的后果是——快照里有**同名历史 mp3**，
于是 `resolveVoiceAsset` 返回了上一轮的旧音频，用户听到的和屏幕上写的对不上。
现在 dev 下把 `/src/assets/...` 直连路径放在候选列表第一位，取不到才回退。
`_t=<时间戳>` 的缓存破除仍然保留，两者缺一不可。

### 相关回归测试

`frontend/src/_tests_/chatAudio.test.ts` 三条用例把上面最容易回退的部分锁住了：
readyState 门控、连续两轮的先停后播、以及**过期请求迟到落定时不得 `pause()`**。
`audioBus.test.ts` 锁住全局单一发声通道。改音频代码后先跑 `npm run test -- --run`。

### 铁律 5：dev 下别让 Vite 监视"后端生成物"目录

`stores/settings.ts` 用 `import.meta.glob(..., { eager: true })` **静态引用**了
`src/assets/voice/**` 与 `src/assets/pictures/**`。这意味着后端每写一个新文件，
Vite 都会判定该模块失效 → HMR 升级为**整页重载** → 刚响起来的语音被掐掉、
控制台被清空、日志再也接不上。排查时极具误导性（会误以为是播放代码的锅）。

`vite.config.ts` 已把这两个目录从 watcher 里排除：

```ts
server: {
  watch: {
    ignored: ['**/.git/**', '**/node_modules/**', '**/dist/**',
              '**/src/assets/voice/**', '**/src/assets/pictures/**'],
  },
},
```

代价是这几个目录里**手工**新增的文件不再进 glob 快照，必须重启 dev server；
而 dev 下的语音本来就走直连磁盘路径（铁律 4 的配套），不依赖快照，所以没有影响。

> 长期建议（未实施）：生成物不该落在 `src/` 里——生产构建根本不会把它们打进 dist。
> 正确做法是后端直接以静态目录暴露（例如 `app.mount("/voice", StaticFiles(...))`），
> 前端用 `VITE_VOICE_BASE` 指向它，彻底绕开 Vite 的模块图。

### 排查用的日志线索（一次就能定位）

| 日志 | 含义 |
|---|---|
| `[音频] play() token=N readyState=… src=…` | 轮询等到数据了，准备播 |
| `[音频] play() 已被接受（token=N）` | 浏览器接受了 play()，**但还不代表真的在响** |
| `[音频] 确认在播: currentTime=1.23 …` | `timeupdate` 触发了 = **确实在解码播放**（这是唯一硬证据） |
| `[音频] 播放中被 stopAudio(<来源>) 打断，调用栈…` | **谁**在播放中途把音频停了，`<来源>` 直接点名（`handleStop` / `playAudio-换新一轮` / `onBeforeUnmount` …） |
| `[音频] 本轮播放已被作废（token N → M）` | 这次播放已被后来的 stopAudio / 新一轮请求顶掉，看上面那条 stopAudio 的栈 |
| `[音频] 音频被外部 pause()` + 调用栈 | 不是本模块停的，是被外部（浏览器策略/扩展/别的发声者）按停的 |
| `[音频] ChatView 挂载 / 卸载` | 组件被重建（HMR 或整页刷新）——重载会顺手掐掉语音并清空控制台 |
