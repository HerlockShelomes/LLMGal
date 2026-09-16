import { defineStore } from 'pinia'
import { DEFAULT_ROLE_LABEL, DEFAULT_ROLE_VALUE } from './settings.ts'

// 定义消息类型
interface Message {
  id: string
  timestamp: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
  hasImage?: boolean
}

// 生成唯一ID：Date.now() 在同一毫秒内的连续操作会碰撞（消息 id 撞车会导致删除/重发错位）。
// crypto.randomUUID 在非安全上下文（http 访问）下不可用，故保留降级实现。
const generateId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

// 内联在 content 里的 base64 图片
const INLINE_IMAGE = /!\[[^\]]*\]\((data:image\/[a-zA-Z0-9.+-]+;base64,[^)]*)\)/g

// 标题结构固定为「角色名-对话N」：换角色名时只替换前缀，序号必须留住。
// 用户手动重命名过的标题（匹配不上）就原样保留，不猜。
const TITLE_SEQ = /-对话(\d+)$/
const replaceTitleRole = (title: string, newLabel: string): string => {
  const seq = title.match(TITLE_SEQ)?.[1]
  return seq ? `${newLabel}-对话${seq}` : title
}

// 持久化前剥离 base64：一张图动辄几 MB，全部写进 localStorage（上限约 5MB）
// 会直接把存储写满并让后续写入抛 QuotaExceededError，整个会话历史都存不进去。
const stripImages = (state: ChatState): ChatState => ({
  ...state,
  conversations: state.conversations.map(conversation => ({
    ...conversation,
    messages: conversation.messages.map(message => ({
      ...message,
      content: typeof message.content === 'string'
        ? message.content.replace(INLINE_IMAGE, '（图片内容未保存）')
        : message.content,
      hasImage: message.hasImage ? false : message.hasImage,
    })),
  })),
})

// 定义Token计数类型
interface TokenCount {
  total: number
  prompt: number
  completion: number
}

// 定义Token使用统计类型
interface TokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

// 定义会话类型
interface Conversation {
  id: string
  title: string
  // 会话绑定的角色（settings 里 RoleOption.value）。角色-会话是强绑定：
  // 进入会话要把角色切回来，切换角色则要另开会话。
  roleName: string
  // 创建时的角色显示名。角色被删掉后会话仍可能残留，留着名字才能显示而不至于空白。
  roleLabel: string
  messages: Message[]
  createdAt: string
  updatedAt: string
  tokenCount: TokenCount
}

// 定义Store的状态类型
interface ChatState {
  conversations: Conversation[]
  activeConversationId: string | null  // 当前展示会话ID
  isLoading: boolean
  currentGeneratingId: string | null  // 当前正在生成回答的会话ID
  // 每个角色各自的会话序号，用于生成「某角色-对话N」。
  // 按角色分开计数，换角色时序号不会互相挤占。
  roleCounters: Record<string, number>
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    conversations: [],
    activeConversationId: null,
    isLoading: false,
    currentGeneratingId: null,
    roleCounters: {},
  }),

  actions: {
    // 创建属于某个角色的新会话
    createConversation(roleName: string = DEFAULT_ROLE_VALUE, roleLabel: string = DEFAULT_ROLE_LABEL) {
      const seq = (this.roleCounters[roleName] ?? 0) + 1
      this.roleCounters[roleName] = seq
      const conversation: Conversation = {
        id: generateId(),
        title: `${roleLabel}-对话${seq}`,
        roleName,
        roleLabel,
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        tokenCount: {
          total: 0,
          prompt: 0,
          completion: 0
        }
      }
      this.conversations.push(conversation)
      this.activeConversationId = conversation.id
      return conversation.id
    },

    // 切换当前会话
    setActiveConversation(id: string) {
      this.activeConversationId = id
    },

    /**
     * 角色标识/名称被改写时，把属于它的会话一起迁过去。
     * 不迁的话会话里的 roleName 会指向一个已经不存在的标识，
     * 进入会话时只能按「角色已删除」处理——那是数据不一致，不是用户想看到的。
     */
    migrateRole(oldValue: string, newValue: string, newLabel: string) {
      if (oldValue === newValue) {
        // 只改名：标题里的角色名得跟着换，否则标题和分组对不上
        this.conversations.forEach(c => {
          if (c.roleName !== oldValue) return
          c.roleLabel = newLabel
          c.title = replaceTitleRole(c.title, newLabel)
        })
        return
      }

      this.conversations.forEach(c => {
        if (c.roleName !== oldValue) return
        c.roleName = newValue
        c.roleLabel = newLabel
        c.title = replaceTitleRole(c.title, newLabel)
      })

      // 计数器一起挪：目标角色已有计数时取较大值，避免两个角色序号撞车
      const moved = this.roleCounters[oldValue]
      if (typeof moved === 'number') {
        this.roleCounters[newValue] = Math.max(this.roleCounters[newValue] ?? 0, moved)
        delete this.roleCounters[oldValue]
      }
    },

    // 删除会话
    deleteConversation(id: string) {
      const index = this.conversations.findIndex(conv => conv.id === id)
      if (index !== -1) {
        const removed = this.conversations[index]
        this.conversations.splice(index, 1)
        // 该角色已无会话：连计数器一起清掉，下次新建又从「对话1」开始。
        // 不清的话会出现「列表里一个会话都没有，新建却是对话7」。
        if (removed && !this.conversations.some(c => c.roleName === removed.roleName)) {
          delete this.roleCounters[removed.roleName]
        }
        if (this.activeConversationId === id) {
          // 如果删除后没有会话，则创建新会话
          if (this.conversations.length === 0) {
            this.createConversation()
          } else {
            // 否则切换到第一个会话
            this.activeConversationId = this.conversations[0]?.id || null
          }
        }
      }
    },

    // 添加消息到当前会话
    addMessage(message: Omit<Message, 'id' | 'timestamp'>) {
      const conversation = this.conversations.find(
        conv => conv.id === this.activeConversationId
      )
      if (conversation) {
        conversation.messages.push({
          id: generateId(),
          timestamp: new Date().toISOString(),
          ...message
        })
        conversation.updatedAt = new Date().toISOString()
      }
    },

    // 按 id 精确删除一条消息
    deleteMessage(id: string) {
      const conversation = this.conversations.find(
        conv => conv.id === this.activeConversationId
      )
      if (!conversation) return
      const index = conversation.messages.findIndex(m => m.id === id)
      if (index === -1) return
      conversation.messages.splice(index, 1)
      conversation.updatedAt = new Date().toISOString()
    },

    // 成对删除一条消息及其紧跟的助手回复。
    // 按 id 定位而不是假定 user/assistant 一定相邻后 splice(index, 2)，
    // 后者在消息被编辑、删除或插入系统消息后会误删下一条无关消息。
    deleteMessagePair(id: string) {
      const conversation = this.conversations.find(
        conv => conv.id === this.activeConversationId
      )
      if (!conversation) return
      const index = conversation.messages.findIndex(m => m.id === id)
      if (index === -1) return

      const target = conversation.messages[index]
      const next = conversation.messages[index + 1]
      const isPair = target.role === 'user' && next?.role === 'assistant'

      conversation.messages.splice(index, isPair ? 2 : 1)
      conversation.updatedAt = new Date().toISOString()
    },

    // 更新正在生成回答的会话的最后一条消息
    updateLastMessage(content: string, reasoning_content?: string) {
      console.log('更新正在生成回答的会话的最后一条消息')
      const conversation = this.conversations.find(
        conv => conv.id === this.currentGeneratingId
      )
      if (conversation && conversation.messages && conversation.messages.length > 0) {
        const lastMessage = conversation.messages[conversation.messages.length - 1]
        if (lastMessage) {
          lastMessage.content = content
          lastMessage.reasoning_content = reasoning_content
          conversation.updatedAt = new Date().toISOString()
        }
      }
    },

    // 把模型思考内容的增量片段追加到正在生成的助手消息上（流式展示）。
    // 思考内容不是正式回复，正式回复到达时由 updateLastMessage(..., '') 清空。
    appendReasoning(delta: string) {
      if (!delta) return
      const conversation = this.conversations.find(
        conv => conv.id === this.currentGeneratingId
      )
      if (!conversation || !conversation.messages.length) return
      const lastMessage = conversation.messages[conversation.messages.length - 1]
      if (!lastMessage) return
      lastMessage.reasoning_content = (lastMessage.reasoning_content || '') + delta
      conversation.updatedAt = new Date().toISOString()
    },

    updateTokenCount(usage: TokenUsage) {
      const conversation = this.conversations.find(
        conv => conv.id === this.activeConversationId
      )
      if (conversation) {
        if (usage.prompt_tokens) {
          conversation.tokenCount.prompt += usage.prompt_tokens
        }
        if (usage.completion_tokens) {
          conversation.tokenCount.completion += usage.completion_tokens
        }
        if (usage.total_tokens) {
          conversation.tokenCount.total += usage.total_tokens
        }
      }
    },

    // 清空当前会话消息
    clearMessages() {
      const conversation = this.conversations.find(
        conv => conv.id === this.activeConversationId
      )
      if (conversation) {
        // 清空消息的同时更新会话时间
        conversation.messages = []
        conversation.updatedAt = new Date().toISOString()
        
        // 确保会话标题保持不变
        if (!conversation.title) {
          conversation.title = `${conversation.roleLabel || DEFAULT_ROLE_LABEL}-对话1`
        }
        conversation.tokenCount = {
          total: 0,
          prompt: 0,
          completion: 0
        }
      }
      
      // 触发状态更新
      this.conversations = [...this.conversations]
    }
  },

  getters: {
    // 获取当前会话
    currentConversation(): Conversation | undefined {
      return this.conversations.find(conv => conv.id === this.activeConversationId)
    },
    
    // 获取当前会话的消息
    currentMessages(): Message[] {
      return this.currentConversation?.messages || []
    },

    // 获取当前会话的 token 统计
    currentTokenCount(): { total: number; prompt: number; completion: number } {
      const conversation = this.currentConversation
      if (!conversation) {
        return { total: 0, prompt: 0, completion: 0 }
      }
      return conversation.tokenCount
    }
  },

  persist: {
    // v2：会话与角色绑定的新结构（旧数据没有 roleName/roleLabel，无法归类，
    // 直接换 key 丢弃；旧键由 main.ts 启动时清掉，不留在 localStorage 里占空间）。
    key: 'ai-chat-history-v2',
    storage: localStorage,
    // 写盘时剥离 base64 图片，只保留文本与必要元数据
    serializer: {
      serialize: (state) => JSON.stringify(stripImages(state as unknown as ChatState)),
      deserialize: (value) => JSON.parse(value),
    },
  },
})