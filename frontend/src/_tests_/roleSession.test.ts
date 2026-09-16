import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from '../stores/chat'
import { DEFAULT_ROLE_VALUE, useSettingsStore } from '../stores/settings'
import {
  resolveRoleNotice,
  roleNotice,
  useRoleGroups,
  useRoleSession,
} from '../composables/useRoleSession'

/**
 * 角色 ↔ 会话绑定的回归测试。
 *
 * 锁死这几条，改动时别踩回去：
 *   1. 会话标题 = 「角色名-对话N」，N 按角色各自计数；
 *   2. 只有有会话的角色才出现分组，会话删光分组随之消失；
 *   3. 进入会话把角色切回去；角色不存在则切默认角色并弹提示；
 *   4. 会话内切换角色必须经确认，取消则不切也不建新会话。
 */
describe('角色与会话绑定', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 弹窗状态是模块级单例，用例之间必须清干净
    resolveRoleNotice(false)
  })

  it('标题格式为「角色名-对话N」，序号按角色各自计数', () => {
    const chat = useChatStore()
    chat.createConversation('Wendy', '温蒂')
    chat.createConversation('Wendy', '温蒂')
    chat.createConversation('Testificate', '测试猫娘')

    expect(chat.conversations.map(c => c.title)).toEqual([
      '温蒂-对话1',
      '温蒂-对话2',
      '测试猫娘-对话1',
    ])
    expect(chat.conversations.every(c => c.roleName)).toBe(true)
  })

  it('按角色分组，会话删光后分组消失', () => {
    const chat = useChatStore()
    const { groups } = useRoleGroups()

    const wendy = chat.createConversation('Wendy', '温蒂')
    chat.createConversation('Testificate', '测试猫娘')

    expect(groups.value.map(g => g.roleValue)).toEqual(['Wendy', 'Testificate'])
    expect(groups.value[0].conversations).toHaveLength(1)

    chat.deleteConversation(wendy)
    expect(groups.value.map(g => g.roleValue)).toEqual(['Testificate'])
  })

  it('进入会话会把角色切到该会话绑定的角色', async () => {
    const chat = useChatStore()
    const settings = useSettingsStore()
    const { enterConversation } = useRoleSession()

    const id = chat.createConversation('GirlProgrammer', '开发的幻想')
    await enterConversation(id)

    expect(settings.RoleConfig.roleName).toBe('GirlProgrammer')
    expect(chat.activeConversationId).toBe(id)
  })

  it('会话角色已删除时切到默认角色并弹窗提示', async () => {
    const chat = useChatStore()
    const settings = useSettingsStore()
    const { enterConversation } = useRoleSession()

    const id = chat.createConversation('GhostRole', '幽灵')
    const pending = enterConversation(id)

    expect(roleNotice.visible).toBe(true)
    expect(roleNotice.message).toContain('该对话线程角色已删除')
    expect(roleNotice.showCancel).toBe(false)

    resolveRoleNotice(true)
    await pending

    expect(settings.RoleConfig.roleName).toBe(DEFAULT_ROLE_VALUE)
    // 会话本身保留，交给用户自己决定要不要删
    expect(chat.conversations).toHaveLength(1)
  })

  it('会话内切换角色：取消则不切换也不新建', async () => {
    const chat = useChatStore()
    const settings = useSettingsStore()
    const { enterConversation, requestRoleSwitch } = useRoleSession()

    const id = chat.createConversation('Wendy', '温蒂')
    await enterConversation(id)
    chat.addMessage({ role: 'user', content: '你好' })

    const pending = requestRoleSwitch('Testificate')
    expect(roleNotice.visible).toBe(true)
    expect(roleNotice.message).toContain('即将切换角色并创建新的对话序列')
    expect(roleNotice.showCancel).toBe(true)

    resolveRoleNotice(false)
    const applied = await pending

    expect(applied).toBe(false)
    expect(settings.RoleConfig.roleName).toBe('Wendy')
    expect(chat.conversations).toHaveLength(1)
  })

  it('会话内切换角色：确认后另开一个属于新角色的会话', async () => {
    const chat = useChatStore()
    const settings = useSettingsStore()
    const { enterConversation, requestRoleSwitch } = useRoleSession()

    const id = chat.createConversation('Wendy', '温蒂')
    await enterConversation(id)
    chat.addMessage({ role: 'user', content: '你好' })

    const pending = requestRoleSwitch('Testificate')
    resolveRoleNotice(true)
    const applied = await pending

    expect(applied).toBe(true)
    expect(settings.RoleConfig.roleName).toBe('Testificate')
    expect(chat.conversations).toHaveLength(2)

    const created = chat.currentConversation
    expect(created?.id).not.toBe(id)
    expect(created?.roleName).toBe('Testificate')
    expect(created?.title).toBe('测试猫娘-对话1')
  })

  it('空会话切换角色时直接改绑，不堆空会话', async () => {
    const chat = useChatStore()
    const settings = useSettingsStore()
    const { enterConversation, requestRoleSwitch } = useRoleSession()

    const id = chat.createConversation('Wendy', '温蒂')
    await enterConversation(id)

    const pending = requestRoleSwitch('Testificate')
    resolveRoleNotice(true)
    await pending

    expect(chat.conversations).toHaveLength(1)
    expect(chat.currentConversation?.id).toBe(id)
    expect(chat.currentConversation?.title).toBe('测试猫娘-对话1')
    expect(settings.RoleConfig.roleName).toBe('Testificate')
  })
})
