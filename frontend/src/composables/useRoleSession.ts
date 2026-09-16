import { computed, reactive } from 'vue'
import { useChatStore } from '../stores/chat.ts'
import {
  DEFAULT_ROLE_LABEL,
  DEFAULT_ROLE_VALUE,
  getDescriptionFile,
  getImageUrl,
  useRoleOptions,
  useSettingsStore,
} from '../stores/settings.ts'

/**
 * 角色 ↔ 会话的绑定逻辑。
 *
 * 为什么要单独拆一个 composable：侧边栏（进入会话）、设置面板（切换角色）、
 * ChatView（首屏初始化）三处都要用同一套规则，各自实现一遍必然走样。
 *
 * 规则只有三条：
 *   1. 会话创建时绑定角色，标题 = 「角色名-对话N」；
 *   2. 进入会话 → 角色切到该会话的角色；角色不存在 → 切默认角色并提示；
 *   3. 在会话里切换角色 → 先确认，确认后另开（或复用空会话）一个属于新角色的会话。
 */

// ---------------------------------------------------------------------------
// 全局单例弹窗
//
// 侧边栏和设置面板都可能触发，但页面上只需要一个弹窗实例：
// 状态提到模块作用域，由 ChatView 挂一个 <RoleNoticeDialog /> 统一渲染。
// ---------------------------------------------------------------------------
export const roleNotice = reactive({
  visible: false,
  message: '',
  // 角色被删的提示只需要「确认」；切换角色的确认需要「确认 + 取消」
  showCancel: false,
  confirmText: '确认',
})

let noticeResolver: ((ok: boolean) => void) | null = null

// 幂等：重复调用不会重复 resolve，也不会因为已经关闭而抛错
export const resolveRoleNotice = (ok: boolean): void => {
  if (!roleNotice.visible) return
  roleNotice.visible = false
  const resolver = noticeResolver
  noticeResolver = null
  resolver?.(ok)
}

const openNotice = (message: string, showCancel: boolean): Promise<boolean> => {
  // 上一个弹窗还没关就又来一个：按「取消」结算掉，避免 promise 悬挂
  resolveRoleNotice(false)
  roleNotice.message = message
  roleNotice.showCancel = showCancel
  roleNotice.visible = true
  return new Promise<boolean>(resolve => {
    noticeResolver = resolve
  })
}

export function useRoleSession() {
  const chatStore = useChatStore()
  const settings = useSettingsStore()
  const roleOptions = useRoleOptions()

  // 角色是否还在（可能被删过）
  const findRole = (value: string) => roleOptions.value.find(r => r.value === value)
  const isRoleAvailable = (value: string) => !!findRole(value)

  // 切角色的同时把立绘与人设文档一起换掉，否则设置面板里显示的还是上一张图
  const applyRole = (value: string): void => {
    settings.updateSettings({
      RoleConfig: {
        roleName: value,
        roleDescription: getDescriptionFile(value),
        roleImage: getImageUrl(value, 'neutral'),
      },
    })
  }

  // 为某个角色创建一个新会话（角色先切过去，再建会话，两者必须一致）
  const createForRole = (value: string): string => {
    const role = findRole(value) ?? {
      value: DEFAULT_ROLE_VALUE,
      label: DEFAULT_ROLE_LABEL,
      type: '虚拟角色' as const,
    }
    applyRole(role.value)
    return chatStore.createConversation(role.value, role.label)
  }

  /**
   * 进入一个已有会话：角色跟着会话走。
   * 角色已被删除 → 切默认角色并弹窗告知（会话本身保留，用户可自行删除）。
   */
  const enterConversation = async (id: string): Promise<void> => {
    const conversation = chatStore.conversations.find(c => c.id === id)
    if (!conversation) return

    chatStore.setActiveConversation(id)

    if (isRoleAvailable(conversation.roleName)) {
      applyRole(conversation.roleName)
      return
    }

    applyRole(DEFAULT_ROLE_VALUE)
    await openNotice('该对话线程角色已删除，切换为默认角色', false)
  }

  /**
   * 在会话内切换角色：先确认，确认后才真正切换并开新会话。
   *
   * 取消时不写 store —— 设置面板的 select 直接双向绑定到 store，
   * store 没变，界面自然回到原角色，不需要额外的回滚代码。
   */
  const requestRoleSwitch = async (value: string): Promise<boolean> => {
    if (!value || value === settings.RoleConfig.roleName) return false

    const ok = await openNotice('即将切换角色并创建新的对话序列，是否执行？', true)
    if (!ok) return false

    const current = chatStore.currentConversation
    // 当前会话还是空的：没有可丢失的内容，直接改绑它，避免侧边栏堆一串空会话。
    // 非空会话则严格按「创建新对话序列」处理。
    if (current && current.messages.length === 0) {
      applyRole(value)
      const role = findRole(value)
      current.roleName = value
      current.roleLabel = role?.label ?? value
      const seq = (chatStore.roleCounters[value] ?? 0) + 1
      chatStore.roleCounters[value] = seq
      current.title = `${current.roleLabel}-对话${seq}`
      return true
    }

    createForRole(value)
    return true
  }

  // 首屏：没有会话就为当前角色建一个；有会话就按「进入会话」的规则对齐角色
  const ensureConversation = (): void => {
    const activeId = chatStore.activeConversationId
    const exists = !!activeId && chatStore.conversations.some(c => c.id === activeId)
    if (exists && activeId) {
      void enterConversation(activeId)
      return
    }
    const current = settings.RoleConfig.roleName
    createForRole(isRoleAvailable(current) ? current : DEFAULT_ROLE_VALUE)
  }

  return {
    roleOptions,
    isRoleAvailable,
    // 删除角色后要静默兜底切到默认角色：那是删除动作的必然结果，
    // 不该再套一层「是否切换」的确认弹窗。
    applyRole,
    enterConversation,
    requestRoleSwitch,
    createForRole,
    ensureConversation,
  }
}

/**
 * 侧边栏的分组视图：按角色把会话归类。
 * 只有存在会话的角色才会出现分组；某个角色的会话被删光，分组自然消失。
 */
export function useRoleGroups() {
  const chatStore = useChatStore()
  const { roleOptions } = useRoleSession()

  type RoleGroup = {
    roleValue: string
    roleLabel: string
    avatar: string
    // 角色已不存在（被删），分组仍保留，方便用户清理残留会话
    missing: boolean
    conversations: typeof chatStore.conversations
  }

  const groups = computed<RoleGroup[]>(() => {
    const source = chatStore.conversations
    const known = roleOptions.value

    const build = (roleValue: string, roleLabel?: string): RoleGroup => {
      const role = known.find(r => r.value === roleValue)
      return {
        roleValue,
        roleLabel: role?.label ?? roleLabel ?? roleValue,
        avatar: getImageUrl(roleValue, 'neutral'),
        missing: !role,
        conversations: source.filter(c => c.roleName === roleValue),
      }
    }

    const result: RoleGroup[] = []
    const seen = new Set<string>()

    // 先按角色列表的固定顺序排，保证分组位置稳定、不会随增删跳来跳去
    for (const role of known) {
      const items = source.filter(c => c.roleName === role.value)
      if (!items.length) continue
      seen.add(role.value)
      result.push(build(role.value, role.label))
    }

    // 已删除角色的残留会话：接在后面，按最早创建时间排序
    const orphans = [...new Set(source.map(c => c.roleName))].filter(v => !seen.has(v))
    orphans
      .sort((a, b) => {
        const ta = source.find(c => c.roleName === a)?.createdAt ?? ''
        const tb = source.find(c => c.roleName === b)?.createdAt ?? ''
        return ta.localeCompare(tb)
      })
      .forEach(v => result.push(build(v)))

    return result
  })

  return { groups }
}
