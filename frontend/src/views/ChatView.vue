<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {Setting} from '@element-plus/icons-vue'
import {useChatStore} from '../stores/chat.ts'
import {
  useModelOptions,
  useRoleOptions,
  useSettingsStore,
  getAudioUrl,
  getAudioUrls,
} from '../stores/settings.ts'
import {messageHandler} from '../utils/messageHandler.ts'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import SettingsPanel from '../components/SettingsPanel.vue'
import SideBar from '../components/SideBar.vue'
import SearchBar from '../components/SearchBar.vue'
import {ElMessage} from 'element-plus'
import {WebSocketManager} from '../utils/WebSocketManager.ts'
// 全局单一发声通道：保证对话语音与设置面板的试听音不会同时响
import {claimPlayback, releasePlayback, stopAllPlayback, isPlaybackOwner} from '../utils/audioBus.ts'
import {
  type AnyServerMessage,
  type ClientMessage,
  ClientMessageType,
  type HistoryMessage,
  type ServerMessage,
  ServerMessageType,
} from "../utils/MessageType.ts"
import { useRSCstore } from "../stores/RoleShowCase.ts";
import {v4 as uuidv4} from 'uuid';

// 初始化聊天存储
const chatStore = useChatStore()
// 计算属性，获取消息列表和加载状态
const currentChatMessages = computed(() => chatStore.currentMessages)
const isLoading = computed(() => chatStore.isLoading)
// 设置面板显示状态
const showSettings = ref(false)
// 消息容器引用，用于滚动到底部
const messagesContainer = ref<HTMLElement | null>(null)
const RSC = useRSCstore()

//更新索引用量
const ind = ref<string>('happy')
const indx = ref<string>('0')
const imgurl = ref<string>('')
const settings = useSettingsStore();

const currentAudioUrl = ref<string>(
    getAudioUrl(settings.RoleConfig.roleName, indx.value)
)


const audio = ref<HTMLAudioElement | null>(null)

// 如果没有活动会话，创建一个新会话
if (!chatStore.activeConversationId) {
  chatStore.createConversation()
}

// 监听消息、对话ID变化，滚动到底部
watch(currentChatMessages, () => {
    // 涉及到页面渲染，需要使用 nextTick
    nextTick(() => {
        if (messagesContainer.value && chatStore.activeConversationId === chatStore.currentGeneratingId) {
            messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
        }
    })
}, { deep: true })

watch(() => chatStore.activeConversationId, () => {
    nextTick(() => {
        if (messagesContainer.value) {
            messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
        }
    })
})

// 多轮上下文：保留最近 20 轮（user + assistant 各算一条，共 40 条）
const HISTORY_ROUND_LIMIT = 20
const HISTORY_MESSAGE_LIMIT = HISTORY_ROUND_LIMIT * 2

// 按会话组织上下文：取当前会话最近 N 条有效消息，按时间正序，
// 只带 role/content 两个字段。endIndex 用于只取某条消息之前的历史（重新生成 / 编辑重发）。
const buildHistory = (endIndex?: number): HistoryMessage[] => {
  const messages = chatStore.currentMessages
  if (!Array.isArray(messages) || messages.length === 0) return []

  const source = typeof endIndex === 'number' ? messages.slice(0, endIndex) : messages

  return source
      .filter(m => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
      .slice(-HISTORY_MESSAGE_LIMIT)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content.trim() }))
      .filter(m => m.content.length > 0)
}

/**
 * 发送消息处理函数
 * @param {string} content 用户输入的消息内容
 * @param {HistoryMessage[]} history 多轮上下文，不含当前这条
 */
const sendViaWebSocket = (content: string, history: HistoryMessage[] = []) => {
  // 统一入口：首次发送、重新生成、编辑重发都走这一条链路，
  // 且都必须带上完整 history，否则后端没有上下文、多轮记忆为零。
  if (!websocketManager) return

  const trimmed = typeof content === 'string' ? content.trim() : ''
  if (!trimmed) {
    ElMessage.warning('发送内容不能为空')
    chatStore.isLoading = false
    chatStore.currentGeneratingId = null
    return
  }

  try {
    const modelOptions = useModelOptions()
    const roleOptions = useRoleOptions()
    // 找不到匹配项（例如 localStorage 里还留着旧的中转站 ID）时，回落成空串，
    // 让后端用自己的 .env 配置，而不是拿一个不存在的模型名去请求厂商。
    const modelText = modelOptions.value.find(m => m.value === settings.modelText) ?? {
      label: '跟随后端配置', value: '', type: 'plain'
    }
    const role = roleOptions.value.find(r => r.value === settings.RoleConfig.roleName) ?? {
      label: '测试猫娘', value: 'Testificate', type: '虚拟角色'
    }

    const userMessage: ClientMessage<ClientMessageType.QUERY> = {
      type: ClientMessageType.QUERY,
      message_id: uuidv4(),
      payload: {
        textModel_config: {
          // 契约要求 text 是 {role, content} 消息对象，不能是裸字符串
          text: { role: 'user', content: trimmed },
          modelText: modelText.value,
        },
        role: role.value,   //角色选择
        imageModel_config: {
          modelImage: settings.modelImage,
          realTimeRendering: false,
        },
        voiceCate: "ElderSister",
        // 多轮上下文：当前会话最近 20 轮，时间正序，不含当前这条
        history,
        sessionId: chatStore.activeConversationId ?? undefined,
      },
    }

    websocketManager.send(userMessage)
    currentRequestId.value = userMessage.message_id

    receives.value.push({
      id: userMessage.message_id,
      sender: "user",
      state: "Sent Message",
    })
  } catch (err) {
    console.error('发送消息失败', err)
    ElMessage.error('消息发送失败，请确认后端服务已启动后重试')
    chatStore.currentGeneratingId = null
    chatStore.isLoading = false

    receives.value.push({
      id: 'Event Detected: Message Sent Failure',
      sender: "user",
      state: "Sent Message",
    })
  }
}

// 统一的入队逻辑：写入用户消息 + 助手占位消息，再通过 WebSocket 发出
const enqueueMessage = (content: string, history: HistoryMessage[] = []) => {
  chatStore.addMessage(messageHandler.formatMessage('user', content))
  chatStore.addMessage(messageHandler.formatMessage('assistant', ''))
  chatStore.isLoading = true
  // 将当前正在生成回复的对话ID设置为活跃对话的ID
  // 这样可以追踪哪个对话正在等待AI响应
  chatStore.currentGeneratingId = chatStore.activeConversationId

  sendViaWebSocket(content, history)
}

/**
 * 清除消息处理函数
 */
const handleClear = () => {
    muteAll('handleClear')
    chatStore.clearMessages()
}

// 处理消息更新（编辑后重发）：同样走 WebSocket，并带上该条之前的历史
const handleWebSocketMessageUpdate = (updatedMessage: { id: string; content: string }) => {
  const index = chatStore.currentMessages.findIndex(m => m.id === updatedMessage.id)
  if (index === -1) return

  // 该条之前的上下文，正序
  const history = buildHistory(index)
  // 按 id 精确删除，避免 splice(index, 2) 误删相邻消息
  chatStore.deleteMessagePair(updatedMessage.id)
  // 重发前停掉上一轮语音，避免新旧声音叠在一起
  muteAll('handleWebSocketMessageUpdate')

  enqueueMessage(updatedMessage.content, history)
}

// 处理消息删除：按 id 精确删除，不再假定 user/assistant 相邻
const handleMessageDelete = (message: { id: string }) => {
  chatStore.deleteMessagePair(message.id)
}

// 处理重新生成：与首次发送统一走 WebSocket，并携带该轮之前的完整 history
const handleRegenerate = (message: { id: string; role: "user" | "assistant"; content: string }) => {
  if (isLoading.value) return

  const index = chatStore.currentMessages.findIndex(m => m.id === message.id && m.role === "assistant")
  if (index <= 0) return

  const userMessage = chatStore.currentMessages[index - 1]
  if (!userMessage || userMessage.role !== 'user') return

  const userContent = userMessage.content
  // 该轮之前的上下文；必须在删除前取，否则会被一起删掉
  const history = buildHistory(index - 1)

  chatStore.deleteMessagePair(userMessage.id)
  // 重新生成前先静音，否则旧语音会和新语音同时响
  muteAll('handleRegenerate')
  enqueueMessage(userContent, history)
}

// 添加暂停处理函数：向后端发送取消报文，而不是中止已经废弃的 HTTP 请求
const handleStop = () => {
  // 先停声音：用户按停止时，上一轮还在播的语音必须立刻安静
  muteAll('handleStop')
  if (currentRequestId.value) {
    try {
      const cancelMessage: ClientMessage<ClientMessageType.CANCEL> = {
        type: ClientMessageType.CANCEL,
        message_id: uuidv4(),
        payload: { target_message_id: currentRequestId.value },
      }
      websocketManager.send(cancelMessage)
    } catch (error) {
      console.warn('取消请求发送失败: ', error)
    }
    currentRequestId.value = null
  }

  // 重置状态
  chatStore.currentGeneratingId = null
  chatStore.isLoading = false
}

/**
 * 后端地址与鉴权令牌改为可配置（写在 frontend/.env.local）：
 *   VITE_WS_URL=ws://localhost:8000/ws/chat
 *   VITE_WS_TOKEN=与后端 .env 里 WS_AUTH_TOKEN 相同的值
 * 后端开启鉴权后，连接必须带 token，否则会被拒绝（AUTH_403）。
 */
function resolveWebSocketUrl(): string {
  const base: string = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/chat'
  const token: string = import.meta.env.VITE_WS_TOKEN || ''
  if (!token) return base
  return `${base}${base.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

// 模型原文形如「(高兴)(因为受到邀请)你好呀」，情绪已由 payload.emotion 单独下发，
// 正文里再显示一遍括号会很难看（后端保留了原文以维持契约，这里在展示层剥离）。
function stripEmotionPrefix(text: string): string {
  if (!text) return ''
  return text.replace(/^\s*(?:\([^()]*\)\s*)+/, '')
}

const WS_Url = resolveWebSocketUrl();
const websocketManager = new WebSocketManager(WS_Url);

const receives = ref<{id: string, sender: "user"|"assistant"|"system", state: string}[]>([]);
const isConnecting = ref(false);
const connectionStatus = ref<'disconnected'|'connecting'|'connected'>('disconnected');
// 已发出、等待响应的 message_id，用于发送取消报文
const currentRequestId = ref<string | null>(null);
// 已尝试的重连次数，配合指数退避使用
const reconnectTimes = ref(0);


// 原先这里是 watch(currentAudioUrl) -> pause() + load()，配合模板上
// :key="audioKey" 重建 <audio> 元素、@canplay 自动 play()。三套机制叠在一起正是
// 「两段语音重叠」的根因：
//   1) load() 会重新触发 canplay，canplay 里无条件 play()，等于把刚 pause 的元素又复活；
//   2) :key 变化会销毁旧元素，但浏览器对「已移出文档的 media element」的 pause 是
//      异步的，在新元素开始播放的瞬间旧元素往往还在发声。
// 现在改成单一命令式路径：元素常驻、src 手动设置、先停后播、并用令牌防止旧请求复活。
let playToken = 0
// 本轮音频的所有定时器（等数据的轮询、自愈复查）。停止时必须全部清掉，
// 否则「停止」两秒后声音又自己响起来。
let playTimers: number[] = []
// 等数据的最长时间与轮询间隔：readyState 到 2 才允许 play()（见下方说明）
const PLAY_WAIT_TIMEOUT = 8000
const PLAY_POLL_INTERVAL = 150
// 「已被接受却仍没响」的自愈复查节奏：每秒一次，最多 4 次
const PLAY_HEAL_INTERVAL = 1000
const MAX_HEAL_TIMES = 4

const clearPlayTimers = () => {
  playTimers.forEach(t => clearTimeout(t))
  playTimers = []
}
const later = (fn: () => void, ms: number) => {
  const t = window.setTimeout(() => {
    playTimers = playTimers.filter(x => x !== t)
    fn()
  }, ms)
  playTimers.push(t)
}

// stopAudio 自己调 pause() 时置位，避免诊断探针把它误报成「外部暂停」
let intentionalPause = false
// 我们是否认为「此刻应该在播」：只有 true 时的 pause 才是可疑的
let expectedPlaying = false
// timeupdate 是否已经报到过（用于区分「play 被接受」和「真的在响」）
let confirmedPlaying = false

const stopAudio = (why = '未标注') => {
  const el = audio.value
  // 递增令牌 = 作废所有在途回调（轮询、play().then()、自愈复查）。
  // 少了这一步，点「停止」之后旧回调仍以为自己是当前请求，会把声音复活。
  const wasPlaying = expectedPlaying || (el ? !el.paused : false)
  playToken++
  clearPlayTimers()
  expectedPlaying = false
  confirmedPlaying = false
  // 只有「确实打断了正在播/在途的音频」才需要惊动排查，正常换源不刷屏
  if (wasPlaying) {
    console.warn(`[音频] 播放中被 stopAudio(${why}) 打断，调用栈:\n${new Error('stopAudio').stack}`)
  }
  if (!el) return
  intentionalPause = true
  try {
    el.pause()
  } finally {
    intentionalPause = false
  }
  try {
    el.currentTime = 0
  } catch {
    // 资源尚未就绪时设置 currentTime 会抛 InvalidStateError，忽略即可
  }
  releasePlayback(el)
}

// 停止一切发声：先作废本元素的待播回调，再停掉全局通道上的其它发声者
const muteAll = (why = '未标注') => {
  stopAudio(`muteAll:${why}`)
  // 这里是 stopAllPlayback 本身，别再写成 muteAll（会无限递归）
  stopAllPlayback()
}

/**
 * 诊断探针：音频元素在「我们以为在播」的时候被外部 pause() 时，打出调用栈。
 * 本模块自己的 stopAudio() 会置 intentionalPause，探针不会误报。
 * 只在元素上装一次。
 */
const installPauseProbe = () => {
  const el = audio.value as (HTMLAudioElement & { __pauseProbed?: boolean }) | null
  if (!el || el.__pauseProbed) return
  el.__pauseProbed = true
  el.addEventListener('pause', () => {
    if (intentionalPause || el.ended) return
    // 不认为在播时（例如 load() 触发的那次 pause）不算故障
    if (!expectedPlaying) return
    // 让位给别的发声者（例如设置面板的试听音）属于正常行为，不是故障
    if (!isPlaybackOwner(el)) return
    console.warn(
      `[音频] 音频被外部 pause()（非 stopAudio 触发）currentTime=${el.currentTime} ` +
      `readyState=${el.readyState}，调用栈:\n${new Error('pause-probe').stack}`
    )
  })
  // 正面证据：元素真的在推进时间轴（timeupdate 只在真正解码播放时才触发）。
  // 有了这条，「play 已被接受」和「确实在响」才区分得开。
  el.addEventListener('timeupdate', () => {
    if (!expectedPlaying || confirmedPlaying) return
    confirmedPlaying = true
    console.log(
      `[音频] 确认在播: currentTime=${el.currentTime.toFixed(2)} ` +
      `duration=${Number.isFinite(el.duration) ? el.duration.toFixed(2) : '未知'} ` +
      `muted=${el.muted} volume=${el.volume} paused=${el.paused}`
    )
  })
}

/**
 * 播放语音。urls 是候选地址列表，按优先级依次尝试：
 * 第一个通常是磁盘上刚生成的最新文件，失败才回退到构建期快照里的历史文件。
 *
 * 铁律（改这里之前先读）：
 *   1. 元素常驻、绝不重建，src 只在这里命令式设置；
 *   2. 「set src → load() → 等 readyState>=2 → play()」四步一个都不能少，
 *      而且绝不能在 readyState<2 时就 play()——此时 play() 的 promise 会被挂住很久，
 *      落定的时候早已是「过期请求」，任何基于它的补刀都会误伤新一轮的音频；
 *   3. 过期请求一律静默忽略，**绝不 pause() 共用的元素**：
 *      同一个 <audio> 上，旧的 play().then() 一旦补刀 pause()，
 *      停掉的是刚开始播的新语音，表现就是「日志说 play 已被接受，但就是没声音」。
 */
const playAudio = (urls: string[]) => {
  const el = audio.value
  if (!el) return

  const candidates = (urls || []).filter(u => !!u)
  if (!candidates.length) {
    // 一个地址都没有：至少要停掉上一轮，否则旧语音会一直响
    stopAudio('playAudio-无候选地址')
    return
  }

  stopAudio('playAudio-换新一轮')
  // stopAudio 已经递增过令牌，这里取当前值即可
  const token = playToken
  // 抢占全局通道：设置面板的试听音等其它发声者会被一起停掉
  claimPlayback(el)
  installPauseProbe()

  let urlIndex = 0

  const attemptNextSource = () => {
    if (token !== playToken) return
    if (urlIndex >= candidates.length) {
      console.warn('[音频] 候选地址全部加载失败：', candidates)
      return
    }
    const url = candidates[urlIndex++]
    // 后端每轮覆盖同名文件，必须破浏览器缓存，否则会播到上一轮的旧音频
    const sep = url.includes('?') ? '&' : '?'
    const finalUrl = `${url}${sep}_t=${Date.now()}`

    // 本地址是否已经作废（加载失败 / 换了下一条）
    let settled = false

    el.addEventListener('error', () => {
      if (token !== playToken || settled) return
      settled = true
      console.warn('[音频] 资源加载失败，换下一个候选地址：', url,
                   '错误码 =', el.error?.code, el.error?.message)
      attemptNextSource()
    }, { once: true })

    el.src = finalUrl
    // 必须显式 load()：只赋值 src 时部分浏览器会推迟加载，readyState 一直停在 0，
    // 表现为「等不到 canplay，也没声音」。
    el.load()

    // 自愈：play() 已被接受，却又变成 paused 且 currentTime 停在 0，
    // 说明有外部因素把它按停了（浏览器策略、其它发声者、扩展……），主动重播。
    let healCount = 0
    const snapshot = () =>
      `paused=${el.paused} readyState=${el.readyState} networkState=${el.networkState} ` +
      `currentTime=${el.currentTime} error=${el.error?.code ?? '无'}`

    const watchPlaybackHealth = () => {
      // 本轮被作废（有新的播放请求，或有人调了 stopAudio）。
      // 这一条以前是静默 return —— 「play 已被接受但什么都没有」正是卡在这里，
      // 所以必须打出来：谁把令牌改了，上面必有 stopAudio 的调用栈。
      if (token !== playToken) {
        console.warn(`[音频] 本轮播放已被作废（token ${token} → ${playToken}），不再自愈`)
        return
      }
      // 通道已被别的发声者抢走（试听音等）：这是正常让位，不能抢回来，
      // 否则两个声音会互相抢麦、循环打架。
      if (!isPlaybackOwner(el)) {
        console.log('[音频] 通道已被其它发声者抢占，本轮不再自愈')
        return
      }
      if (!el.paused || el.currentTime > 0) {
        console.log(`[音频] 播放正常: ${snapshot()}`)
        return
      }
      if (el.readyState < 2 || healCount >= MAX_HEAL_TIMES) {
        console.warn(`[音频] 播放没起来且已放弃自愈: ${snapshot()}`)
        return
      }
      healCount++
      console.warn(`[音频] 播放被中断，第 ${healCount} 次自愈重播: ${snapshot()}`)
      el.play().catch(() => { /* 下一次复查再试 */ })
      later(watchPlaybackHealth, PLAY_HEAL_INTERVAL)
    }

    const startPlayback = () => {
      if (token !== playToken || settled) return
      console.log(
        `[音频] play() token=${token} readyState=${el.readyState} ` +
        `networkState=${el.networkState} src=${el.currentSrc || el.src}`
      )
      // 浏览器可能拦截自动播放，必须 catch，否则会抛未捕获的 Promise 异常
      el.play().then(() => {
        // 已经是过期请求：静默忽略。绝不 pause()——那是同一个元素，
        // 停掉的是当前正在响的新语音。
        if (token !== playToken) return
        expectedPlaying = true
        console.log(`[音频] play() 已被接受（token=${token}），等 timeupdate 确认）`)
        later(watchPlaybackHealth, PLAY_HEAL_INTERVAL)
      }).catch((error: unknown) => {
        if (token !== playToken) return
        console.warn('[音频] play() 被拒绝（多为浏览器自动播放策略）:', error)
        ElMessage.warning({
          message: '浏览器拦截了自动播放，点击页面任意位置后再试一次',
          duration: 5000,
          showClose: true,
        })
      })
    }

    // 轮询等数据：readyState>=2（HAVE_CURRENT_DATA）才 play()。
    // 不再依赖 canplay/loadedmetadata 事件——事件一旦没触发就永远静默，
    // 而超时兜底在 readyState=0 时硬播又正是「promise 迟到落定」的源头。
    const deadline = Date.now() + PLAY_WAIT_TIMEOUT
    const waitForData = () => {
      if (token !== playToken || settled) return
      if (el.readyState >= 2) {
        startPlayback()
        return
      }
      if (Date.now() >= deadline) {
        console.warn(
          `[音频] 等待数据超时: readyState=${el.readyState} ` +
          `networkState=${el.networkState} src=${el.currentSrc || el.src}`
        )
        return
      }
      later(waitForData, PLAY_POLL_INTERVAL)
    }

    later(waitForData, PLAY_POLL_INTERVAL)
  }

  attemptNextSource()
}

const handleAudioEnded = () => {
  // 正常播完，此后不该再有「外部 pause」的告警
  expectedPlaying = false
  const el = audio.value
  if (el) releasePlayback(el)
}



function isAssistantResponse(
    message: AnyServerMessage
): message is ServerMessage<ServerMessageType.RESPONSE> {
  return message.type === ServerMessageType.RESPONSE;
}

function isErrorResponse(
    message: AnyServerMessage
): message is ServerMessage<ServerMessageType.ERROR> {
  return message.type === ServerMessageType.ERROR;
}

const handleServerMessage = (data: AnyServerMessage) => {
  if (isAssistantResponse(data)) {
    const resp = data.payload.response ?? '';
    const emo = data.payload.emotion ?? 'neutral';
    const i = data.payload.index ?? '0';
    const imaUrl = data.payload.imageUrl ?? '';

    ind.value = emo;
    RSC.emotion = emo;
    indx.value = i;
    RSC.index = i;
    imgurl.value = imaUrl;

    // 展示给用户的正文要剥掉开头的情绪括号（语音侧后端已处理，这里处理文本展示）
    chatStore.updateLastMessage(stripEmotionPrefix(resp), '');

    // 显式播放，不再依赖 currentAudioUrl 的 watch：
    // index 与上一轮相同时 watch 根本不会触发，新一轮的语音就永远播不出来。
    // 传候选列表而不是单一地址：dev 下优先磁盘上的最新 wav，
    // 该文件还没生成时自动回退到构建期快照里的历史素材。
    const audioCandidates = getAudioUrls(settings.RoleConfig.roleName, RSC.index)
    currentAudioUrl.value = audioCandidates[0] ?? ''
    playAudio(audioCandidates)

    // 重置正在生成回复的对话ID为null,表示当前没有对话在等待AI响应
    chatStore.currentGeneratingId = null
    chatStore.isLoading = false
    currentRequestId.value = null

    // partial 表示文本已成功但语音或图片生成失败：文本照常显示，只做轻微提示
    if (data.status === 'partial') {
      ElMessage.warning('回复已生成，但语音或图片生成失败')
    }
  } else if (data.type === ServerMessageType.PROGRESS) {
    console.log('stream', data.payload);
  } else if (isErrorResponse(data)) {
    // 正文要展示可读的错误原因：payload.message 优先，退到 detail / code
    const reason = data.payload?.message
        || data.payload?.detail
        || data.payload?.code
        || '服务器返回未知错误'
    console.error('Server Error', data.payload);
    ElMessage.error({
      message: reason,
      duration: 5000,
      showClose: true,
    })

    receives.value.push({
      id: data.message_id,
      sender: 'assistant',
      state: 'Error',
    });

    chatStore.updateLastMessage(`请求失败：${reason}`, '')
    chatStore.currentGeneratingId = null
    chatStore.isLoading = false
    currentRequestId.value = null
  } else {
    console.warn('未知消息类型: ', data);
  }
};

// 连接成功：重置退避计数，否则一次成功的重连之后仍会很快触及上限
const handleConnected = () => {
  connectionStatus.value = 'connected';
  isConnecting.value = false;
  reconnectTimes.value = 0;
  receives.value.push({
    id: "Event Detected: Connected",
    sender: "system",
    state: "Connected",
  });
};

// 断开连接：有限次数的指数退避重连，不做无限重连
const handleDisconnected = () => {
  connectionStatus.value = 'disconnected';
  isConnecting.value = false;
  receives.value.push({
    id: "Event Detected: Disconnected",
    sender: "system",
    state: "Disconnected",
  });

  scheduleReconnect();
};

const handleErrorEvent = (error: unknown) => {
  console.error('WebSocket Error: ', error);
  receives.value.push({
    id: "Event Detected: Error",
    sender: "system",
    state: "Error",
  });
};

// 后端判定 payload 非法（缺 role / modelText / realTimeRendering，或 text 是裸字符串）
// 必须提示用户，不能静默吞掉，否则界面会一直卡在"正在思考"
const handleInvalidMessage = (data: unknown) => {
  const payload = data as { type?: string; reason?: string; payload?: { reason?: string } } | null
  // 拿不到 reason 说明是被误判成非法的报文（例如后端的 pong），
  // 至少把 type 打出来，别再让用户只能看到「未知原因」。
  const reason = payload?.payload?.reason
    || payload?.reason
    || `后端返回了无法识别的报文（type=${payload?.type ?? '未知'}）`

  console.warn('后端返回 invalid_message: ', data);
  ElMessage.warning({
    message: `请求被后端拒绝：${reason}`,
    duration: 5000,
    showClose: true,
  })

  receives.value.push({
    id: "Event Detected: Invalid Message",
    sender: "system",
    state: "Invalid Message",
  });

  chatStore.currentGeneratingId = null
  chatStore.isLoading = false
  currentRequestId.value = null
};

// 监听器只注册一次：initWebSocket 每次重连都会被调用，
// 若在内部注册，同一个处理器会被叠加多次，导致一条响应被处理多遍。
const handleConnectionEvents = () => {
  websocketManager.on('connected', handleConnected);
  websocketManager.on('disconnected', handleDisconnected);
  websocketManager.on('error', handleErrorEvent);
  websocketManager.on('message', handleServerMessage);
  websocketManager.on('invalid_message', handleInvalidMessage);
  websocketManager.on('parse_error', handleErrorEvent);
};

handleConnectionEvents();

const initWebSocket = async () => {
  if (isConnecting.value) return
  try{
    isConnecting.value = true;
    connectionStatus.value = 'connecting';
    receives.value.push({
      id: "Event Established: Connecting",
      sender: "system",
      state: "Connecting",
    });

    // 监听器已在调用前注册完毕，connected 事件才不会在注册之前就触发掉
    await websocketManager.connect();
  } catch (error) {
    console.error('Connecting Process Failed: ',error);
    isConnecting.value = false;
    connectionStatus.value = 'disconnected';
    receives.value.push({
      id: "Event Detected: Connection Failure",
      sender: "system",
      state: "Error",
    });
  }
};

// 指数退避重连，最多 MAX_RECONNECT_TIMES 次；达到上限后提示用户而不是继续重连
const MAX_RECONNECT_TIMES = 5
let reconnectTimer: number | null = null

const scheduleReconnect = () => {
  if (reconnectTimer !== null) return

  if (reconnectTimes.value >= MAX_RECONNECT_TIMES) {
    ElMessage.error('与后端的连接已断开，请检查后端服务后刷新页面重试')
    return
  }

  const delay = Math.min(1000 * 2 ** reconnectTimes.value, 30_000)
  reconnectTimes.value++
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    initWebSocket()
  }, delay)
}

// 首次发送：历史必须在写入本次消息之前取，这样天然不含当前这条
const handleSendbyWebSocket = (content: string) => {
  const history = buildHistory()
  enqueueMessage(content, history)
}


onMounted (() => {
  // 「组件被重建」的探针：Vite HMR / 整页刷新都会在这里留痕
  console.log('[音频] ChatView 挂载（每次重建都会打印）')
  // 探针要在任何一次播放之前装好，才能抓到「播放前就被按停」的情况
  installPauseProbe();
  try{
    initWebSocket();
  } catch (error) {
    console.log('Error', error);
  }

});

onBeforeUnmount(() => {
  // 组件销毁时浏览器不会自动静音仍在播放的 audio，必须显式停掉。
  // 这条日志同时也是「页面/组件被重建」的探针：Vite HMR 或整页刷新都会走到这里，
  // 而重建会顺带把正在播的语音掐掉。
  console.warn(`[音频] ChatView 卸载，停掉音频。调用栈:\n${new Error('unmount').stack}`)
  muteAll('onBeforeUnmount')
  // 卸载时移除监听、关闭连接、清理重连定时器，
  // 否则定时器仍会在组件销毁后触发 connect()，回调打到已卸载的组件上。
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  websocketManager.off('connected', handleConnected);
  websocketManager.off('disconnected', handleDisconnected);
  websocketManager.off('error', handleErrorEvent);
  websocketManager.off('message', handleServerMessage);
  websocketManager.off('invalid_message', handleInvalidMessage);
  websocketManager.off('parse_error', handleErrorEvent);
  websocketManager.disconnect();
})

</script>

<template>
    <div class="app-container">
        <!-- 侧边栏 -->
        <side-bar />

        <!-- 聊天容器 -->
        <div class="chat-container">
            <!-- 聊天头部，包含标题和设置按钮 -->
            <div class="chat-header">
                <h1>LLM Galgame</h1>
                <search-bar />
                <el-button circle :icon="Setting" @click="showSettings = true" />
            </div>

            <!-- 消息容器，显示对话消息 -->
            <div class="messages-container" ref="messagesContainer">
                <template v-if="currentChatMessages.length">
                    <chat-message v-for="message in currentChatMessages" :key="message.id" :message="message"
                        @update="handleWebSocketMessageUpdate" @delete="handleMessageDelete"
                        @regenerate="handleRegenerate" />
                </template>
                <div v-else class="empty-state">
                    <el-empty description="开始对话吧" />
                </div>
            </div>

            <!-- 聊天输入框 -->
            <chat-input :loading="isLoading" :generating="chatStore.currentGeneratingId !== null"
                        @send="handleSendbyWebSocket" @clear="handleClear" @stop="handleStop"
                        :ix="RSC.emotion"
            />

            <!-- 设置面板 -->
            <settings-panel v-model="showSettings" />
          <!-- 常驻的单一音频元素：src 由 playAudio() 命令式设置。
               不再用 :key 重建元素，也不再靠 <source> + @canplay 自动播放——
               那套写法会让旧元素在被移除前继续发声，造成两段语音重叠。 -->
          <audio ref="audio" preload="auto" @ended="handleAudioEnded" />
        </div>
    </div>
</template>

<style lang="scss" scoped>
.app-container {
  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

/* 定义聊天容器的样式，占据整个视口高度，使用flex布局以支持列方向的布局 */
.chat-container {
    flex: 1;
    min-width: 0; /* 防止内容溢出 */
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden; /* 控制溢出 */
}

/* 设置聊天头部的样式，包括对齐方式和背景色等 */
.chat-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background-color: var(--bg-color);
    border-bottom: 1px solid var(--border-color);

    /* 设置聊天头部标题的样式，无默认间距，自定义字体大小和颜色 */
    h1 {
        margin: 0;
        font-size: 1.5rem;
        color: var(--text-color-primary);
    }
}

/* 定义消息容器的样式，占据剩余空间，支持滚动，自定义背景色 */
.messages-container {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    background-color: var(--bg-color-secondary);
}

/* 设置空状态时的样式，占据全部高度，居中对齐内容 */
.empty-state {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}
</style>