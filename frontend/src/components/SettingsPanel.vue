<script setup lang="ts">
import {reactive, computed, ref, watch, watchEffect, onBeforeUnmount} from 'vue'
import {
  useSettingsStore,
  useModelOptions,
  type ModelOption,
  useRoleOptions,
  useRoleImage,
  getDescriptionFile,
  getTestAudioUrls,
  ROLE_VOICE_LABELS,
  VOICE_CATEGORY_GROUPS,
  VOICE_OPTIONS,
  API_BASE,
  staticUrl,
  APP_MODE_LABELS,
  type AppMode,
  type CustomRoleDetail,
  type RoleOption,
  defaultRole,
  DEFAULT_ROLE_VALUE,
  DEFAULT_ROLE_LABEL,
} from '../stores/settings.ts'
import { useChatStore } from '../stores/chat.ts'
// 全局单一发声通道：试听音与 ChatView 的对话语音互斥
import {claimPlayback} from '../utils/audioBus.ts'
import {stopWatchingAll, watchRoleCreation} from '../utils/roleCreation.ts'
// 运行时模式（Mock / 正式版）：真相源在后端，这里只负责显示与触发切换
import {switchAppMode, syncAppModeFromBackend} from '../utils/appMode.ts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Plus, InfoFilled } from '@element-plus/icons-vue'
import { ElTooltip } from 'element-plus'
// 角色切换不再是「改一个字段」，而是会牵动会话（另开一个属于新角色的会话）
import { useRoleSession } from '../composables/useRoleSession.ts'

// 定义组件的props
const props = defineProps({
  modelValue: Boolean
})

// 定义组件的emits
const emit = defineEmits(['update:modelValue'])

// 使用设置存储
const settingsStore = useSettingsStore()
const modelOptions = useModelOptions()
const roleOptions = useRoleOptions()
const { requestRoleSwitch, applyRole } = useRoleSession()
const chatStore = useChatStore()

/**
 * 角色下拉框直接绑定 store，而不是面板里的副本。
 * 这样一来「取消切换」不需要任何回滚代码 —— store 没变，界面自然回到原角色。
 */
const onRoleChange = (value: string) => {
  void requestRoleSwitch(value)
}

// 可见性计算属性，同步抽屉的可见性状态
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// 设置对象，使用reactive进行响应式处理
const settings = reactive({
  isDarkMode: settingsStore.isDarkMode,
  modelText: settingsStore.modelText,
  modelVoice: settingsStore.modelVoice,
  modelImage: settingsStore.modelImage,
  temperature: settingsStore.temperature,
  maxTokens: settingsStore.maxTokens,
  apiKey: settingsStore.apiKey,
  streamResponse: settingsStore.streamResponse,
  topP: settingsStore.topP,
  topK: settingsStore.topK,
  frequencyPenalty: settingsStore.frequencyPenalty,
  t2iConfig: {
    imageSize: settingsStore.t2iConfig.imageSize,
    inferenceSteps: settingsStore.t2iConfig.inferenceSteps
  },
  RoleConfig: {
    roleName: settingsStore.RoleConfig.roleName,
    roleDescription: settingsStore.RoleConfig.roleDescription,
    roleImage: settingsStore.RoleConfig.roleImage,
  }
})

// 「保存设置」会把整个 settings 副本写回 store，
// 角色字段必须始终与 store 一致，否则会把被弹窗拦截下来的切换又写回去。
watch(
  () => settingsStore.RoleConfig.roleName,
  (value) => { settings.RoleConfig.roleName = value },
)




// 现阶段只允许文本模型发生更改。

// 新增：控制添加/编辑模型对话框的显示
const modelDialogVisible = ref(false)
const isEditing = ref(false)

const currentTextModel = ref<ModelOption>({
  label: '',
  value: '',
  type: 'plain'
})


// const currentVoiceModel = ref<ModelOption>({
//   label: '',
//   value: '',
//   type: 'voice'
// })
// const currentImageModel = ref<ModelOption>({
//   label: '',
//   value: '',
//   type: 'text2img'
// })

const originalModelValue = ref('')

// 检查模型value是否重复
const checkModelValueExists = (value: string, excludeValue?: string) => {
  // 检查是否与默认模型重复
  const defaultModelExists = modelOptions.value
    .filter(model => !settingsStore.customModels.includes(model))
    .some(model => model.value === value)
  
  if (defaultModelExists) {
    return '模型标识与默认模型重复'
  }


  // 检查是否与其他自定义模型重复(排除当前编辑的模型)
  const customModelExists = settingsStore.customModels
    .some(model => model.value === value && model.value !== excludeValue)
  
  if (customModelExists) {
    return '模型标识已存在'
  }

  return ''
}

// 已删除 checkRoleOverlap：该函数从未被任何地方调用（无自定义角色新增入口会用到它），
// 在 vue-tsc 的 noUnusedLocals 下直接让 npm run build 失败。
// 后续若要支持"新增自定义角色"，在这里照 checkModelOverlap 的写法接上即可。

// ----------------------------------------------------------------------------
// 运行时模式（Mock / 正式版）
//
// 判定发生在后端每一轮请求上，所以切换后无需刷新页面、也不影响正在播放的音频；
// 前端只做两件事：显示当前模式、把用户的选择发给后端。
// ----------------------------------------------------------------------------
const modeSwitching = ref(false)
const isMockMode = computed(() => settingsStore.appMode === 'mock')
const appModeLabel = computed(() => APP_MODE_LABELS[settingsStore.appMode])

const toggleAppMode = async () => {
  if (modeSwitching.value) return
  const target: AppMode = isMockMode.value ? 'prod' : 'mock'
  modeSwitching.value = true
  try {
    const state = await switchAppMode(target)
    // 失败时 switchAppMode 已经提示过，这里保持界面原状即可
    if (!state) return
    settingsStore.setAppMode(state.mode)
    if (state.mode === 'mock') {
      ElMessage.success('已切换到 Mock 版：AI 不再接入回复，音频与图像固定为测试内容')
    } else {
      ElMessage.success('已切换回正式版：AI 已接入，所有基础功能可正常使用')
    }
  } finally {
    modeSwitching.value = false
  }
}

// 打开设置面板时与后端对一次账：可能被另一个标签页切过，或手工改过开关文件。
// 不这样做的话，界面会拿一份过期的本地镜像骗用户。
watch(visible, (open) => {
  if (open) syncAppModeFromBackend()
})

// 处理深色模式切换
const handleDarkModeChange = () => {
  settingsStore.toggleDarkMode()
}

// 保存设置
const handleSave = () => {
  settingsStore.updateSettings(settings)
  ElMessage.success('设置已保存')
  visible.value = false
}

// 打开添加模型对话框
const showAddModelDialog = () => {
  isEditing.value = false
  currentTextModel.value = {
    label: '',
    value: '',
    type: 'plain'
  }
  modelDialogVisible.value = true
}

// 打开编辑模型对话框
const showEditModelDialog = (model: ModelOption) => {
  isEditing.value = true
  currentTextModel.value = { ...model }
  originalModelValue.value = model.value
  modelDialogVisible.value = true
}

// 保存模型
const handleSaveModel = () => {
  if (!currentTextModel.value.label || !currentTextModel.value.value) {
    ElMessage.warning('请填写完整的模型信息')
    return
  }

  // 检查value值是否重复
  const errorMsg = checkModelValueExists(
    currentTextModel.value.value,
    isEditing.value ? originalModelValue.value : undefined
  )
  
  if (errorMsg) {
    ElMessage.warning(errorMsg)
    return
  }

  if (isEditing.value) {
    settingsStore.editCustomModel(originalModelValue.value, currentTextModel.value)
    if (settings.modelText === originalModelValue.value) {
      settings.modelText = currentTextModel.value.value
    }
  } else {
    settingsStore.addCustomModel(currentTextModel.value)
  }

  modelDialogVisible.value = false
  ElMessage.success(isEditing.value ? '模型已更新' : '模型已添加')
}

// 删除模型
const handleDeleteModel = async (model: ModelOption) => {
  try {
    await ElMessageBox.confirm('确定要删除这个模型吗？', '警告', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    // 删除模型
    settingsStore.removeCustomModel(model.value)
    
    // 如果删除的是当前选中的模型,切换到默认模型
    if (settings.modelText === model.value) {
      // 获取第一个非自定义模型作为默认模型
      const defaultModel = modelOptions.value.find(m => !settingsStore.customModels.includes(m))
      if (defaultModel) {
        settings.modelText = defaultModel.value
      }
    }
    
    ElMessage.success('模型已删除')
  } catch {
    // 用户取消删除
  }
}

// 获取模型类型标签文字
const getModelTypeLabel = (type: string) => {
  const typeMap: Record<string, string> = {
    'plain': '普通',
    'visual': '图生图',
    'text2img': '文生图',
    'voice': '语音'
  }
  return typeMap[type] || type
}

// ---------------------------------------------------------------------------
// 自定义角色的增删
//
// store 里早就有 addNewRole / editCustomRole / removeCustomRole 三个 action，
// 但一直没有 UI 入口（原位置只有一句「此处需要完善增删角色逻辑」的注释）。
// 这里照模型的增删写法接上。
// ---------------------------------------------------------------------------
const roleDialogVisible = ref(false)
const isRoleEditing = ref(false)
const originalRoleValue = ref('')

const currentRole = ref<RoleOption>({
  label: '',
  value: '',
  type: '虚拟角色'
})

// 角色标识重复检查：内置角色与已有自定义角色都不能撞
const checkRoleValueExists = (value: string, excludeValue?: string): string => {
  if (defaultRole.some(role => role.value === value)) {
    return '角色标识与内置角色重复'
  }
  if (settingsStore.customRoles.some(role => role.value === value && role.value !== excludeValue)) {
    return '角色标识已存在'
  }
  return ''
}

const showAddRoleDialog = () => {
  isRoleEditing.value = false
  currentRole.value = { label: '', value: '', type: '虚拟角色' }
  roleDialogVisible.value = true
}

const showEditRoleDialog = (role: RoleOption) => {
  isRoleEditing.value = true
  currentRole.value = { ...role }
  originalRoleValue.value = role.value
  roleDialogVisible.value = true
}

const handleSaveRole = () => {
  const { label, value, type } = currentRole.value
  if (!label.trim() || !value.trim()) {
    ElMessage.warning('请填写完整的角色信息')
    return
  }

  const errorMsg = checkRoleValueExists(value.trim(), isRoleEditing.value ? originalRoleValue.value : undefined)
  if (errorMsg) {
    ElMessage.warning(errorMsg)
    return
  }

  if (isRoleEditing.value) {
    settingsStore.editCustomRole(originalRoleValue.value, { label: label.trim(), value: value.trim(), type })
    // 会话是按角色标识绑定的，标识一改必须把老会话一起迁过去，
    // 否则它们会立刻变成「角色已删除」状态。
    chatStore.migrateRole(originalRoleValue.value, value.trim(), label.trim())

    // 编辑的正好是当前角色：同步 RoleConfig，否则面板里显示的名字是旧的
    if (settingsStore.RoleConfig.roleName === originalRoleValue.value) {
      applyRole(value.trim())
    }
  } else {
    settingsStore.addNewRole({ label: label.trim(), value: value.trim(), type })
  }

  roleDialogVisible.value = false
  ElMessage.success(isRoleEditing.value ? '角色已更新' : '角色已添加')
}

const handleDeleteRole = async (role: RoleOption) => {
  // 该角色名下的会话不会被一起删掉：它们会留在侧边栏并标成「已删除」，
  // 由用户自己决定留不留。这一点必须在确认框里讲清楚，否则等于静默丢数据。
  const owned = chatStore.conversations.filter(c => c.roleName === role.value).length
  const extra = owned ? `该角色名下还有 ${owned} 个会话，删除角色后它们会保留在侧边栏并标记为「已删除」。` : ''
  try {
    await ElMessageBox.confirm(`确定要删除角色「${role.label}」吗？${extra}`, '警告', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }

  settingsStore.removeCustomRole(role.value)

  // 删掉的正好是当前角色：静默切到默认角色（删除的必然结果，不再弹确认）
  if (settingsStore.RoleConfig.roleName === role.value) {
    applyRole(DEFAULT_ROLE_VALUE)
    ElMessage.info(`角色已删除，已切换为默认角色「${DEFAULT_ROLE_LABEL}」`)
  } else {
    ElMessage.success('角色已删除')
  }
}

// 角色增删的四个入口在 main 工作区里就没有 UI 按钮挂载（半成品）。
// 先显式暴露给父组件：既保留实现，又不会被 noUnusedLocals 判成死代码。
// 后续在模板里接上按钮后，删掉这一行即可。
defineExpose({ showAddRoleDialog, showEditRoleDialog, handleSaveRole, handleDeleteRole })

// 获取标签类型
const getModelTagType = (type: string) => {
  const typeMap: Record<string, '' | 'success' | 'warning' | 'info'> = {
    'plain': '',
    'visual': 'success',
    'text2img': 'success',
    'voice': 'warning'
  }
  return typeMap[type] || 'info'
}

const getRoleTagType = (type: string) => {
  const typeMap: Record<string, '' | 'success' | 'warning' | 'info'> = {
    '虚拟角色': 'warning',
    '数字分身': 'success',
  }
  return typeMap[type] || 'info'
}


// 图片尺寸选项
const imageSizeOptions = [
  { label: '1024x1024', value: '1024x1024' },
  { label: '960x1280', value: '960x1280' },
  { label: '768x1024', value: '768x1024' },
  { label: '720x1440', value: '720x1440' },
  { label: '720x1280', value: '720x1280' }
]

// 添加当前选中模型的类型计算属性
const currentModelText = computed(() => {
    const model = modelOptions.value.find(m => m.value === settings.modelText)
    return model?.type || 'plain'
})

const currentModelImage = computed(() => {
  const model = modelOptions.value.find(m => m.value === settings.modelImage)
  return model?.type || 'text2img'
})

// const currentRole = computed(() => {
//   const role = roleOptions.value.find(r => r.value === settings.RoleConfig.roleName)
//   return role?.type || '虚拟角色'
// })

const plainModelType = computed(() => {
  return modelOptions.value.filter(m => m.type === 'plain')
})

const text2picModelType = computed(() => {
  return modelOptions.value.filter(m => (m.type === 'text2img')||(m.type === 'visual'))
})

const voiceModelType = computed(() => {
  return modelOptions.value.filter(m => m.type === 'voice')
})

// 是否显示LLM/VLM相关设置
const showLLMSettings = computed(() => {
    return ['plain'].includes(currentModelText.value)
})

// 是否显示文生图相关设置
const showT2ISettings = computed(() => {
    return (currentModelImage.value === 'text2img') || (currentModelImage.value === 'visual')
})

// const logDebugInfo = (path: string, success: boolean) => {
//   if (import.meta.env.MODE === 'development') {
//     console.groupCollapsed('[文件加载调试]')
//     console.log('请求文件名: ', 'test')
//     console.log('完整路径: ', path)
//     console.log('加载状态: ', success ? '成功' : '失败')
//     console.groupEnd()
//   }
// }
//
// const loadFileContent = async (fileName: string) => {
//   try {
//     loading.value = true
//     errorMsg.value = ''
//     currentFilePath.value = getDescriptionFile(fileName)
//     if (import.meta.env.DEV) {
//       console.log('[DEV] 正在请求文件路径: ', currentFilePath.value)
//     }
//
//     const response = await fetch(currentFilePath.value)
//
//     if (!response.ok) {
//       throw new Error(`HTTP错误: ${response.status}`)
//     }
//
//
//     fileContent.value = await response.text()
//     errorMsg.value = ''
//
//     logDebugInfo(currentFilePath.value, true)
//   } catch (err) {
//     errorMsg.value = `加载失败: ${err instanceof Error ? err.message : '未知错误'}`
//
//     if (import.meta.env.DEV) {
//       console.error('文件加载错误: ', err)
//     }
//
//     logDebugInfo(currentFilePath.value, false)
//   } finally {
//     loading.value = false
//   }
// }


const content = ref<string>('')
const errorMessage = ref<string>('')

// 角色立绘：候选逐级回退（glob → dev 直连磁盘 → 后端 /static）。
// 每个候选加载失败就试下一个，全部失败 url 为空串 → 显示「显示失败」占位符。
// 直接读 store：面板里的副本只是「保存设置」时的载荷，
// 角色相关的展示一律以 store 为准，避免取消切换后界面还停在新角色上。
const roleImage = useRoleImage(
  () => settingsStore.RoleConfig.roleName,
  () => 'neutral',
)
const roleImageUrl = roleImage.url
const roleDocUrl = computed(() => getDescriptionFile(settingsStore.RoleConfig.roleName))

const handleImageError = () => {
  roleImage.onError()
  // 所有候选都试完仍失败，才提示缺失
  if (!roleImage.url.value) {
    ElMessage.warning('角色图片缺失')
  }
}

watchEffect(async () => {
  const currentRole = settingsStore.RoleConfig.roleName
  // 自定义角色：详情已在前端保存，直接展示其性格设定，无需再请求磁盘 txt
  const detail = settingsStore.customRoleDetails[currentRole]
  if (detail?.personality) {
    content.value = detail.personality
    errorMessage.value = ''
    return
  }
  try {
    const docContent = await fetch(roleDocUrl.value)
            .then(read => read.ok ? read.text():Promise.reject('文档不存在'))
    content.value = docContent
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = `加载 ${currentRole} 文档失败: ${error instanceof Error ? error.message:error}`
    content.value = ''
  }

})

// 常驻的单一音频元素：不再用 :key 重建（旧元素被移除后仍可能继续发声，
// 与对话语音叠在一起）。角色切换时在 play() 里手动改 src + load() 即可。
const audio = ref<HTMLAudioElement | null>(null)

// 仅用于展示：真正发声用的是 backend/config.py 的 ROLE_VOICES
const currentVoiceLabel = computed(() => {
  const name = settingsStore.RoleConfig.roleName
  const detail = settingsStore.customRoleDetails[name]
  if (detail?.voiceId) {
    const v = VOICE_OPTIONS.find(x => x.id === detail.voiceId)
    return v ? `${v.name}（${v.desc}）` : detail.voiceId
  }
  return ROLE_VOICE_LABELS[name] ?? '未配置（沿用默认音色）'
})

// 试听播放令牌：换角色/重复点击时作废上一次的在途回调
let testPlayToken = 0

const play = () => {
  const el = audio.value
  if (!el) return

  const urls = getTestAudioUrls(settingsStore.RoleConfig.roleName)
  if (!urls.length) {
    ElMessage.warning('没有找到该角色的试听音频，请重新生成后再试')
    return
  }

  // 抢占全局发声通道：正在播放的对话语音会被停掉，反之亦然
  claimPlayback(el)

  const token = ++testPlayToken
  let index = 0

  const attempt = () => {
    if (token !== testPlayToken) return
    if (index >= urls.length) {
      console.warn('[试听] 候选地址全部加载失败：', urls)
      ElMessage.warning('试听音频加载失败，请检查资源文件是否存在')
      return
    }
    const url = urls[index++]
    let settled = false

    // 该地址不可用（例如 dev 直连的 wav 还没生成）：换下一个候选
    el.addEventListener('error', () => {
      if (token !== testPlayToken || settled) return
      settled = true
      console.warn('[试听] 资源加载失败，换下一个候选地址：', url)
      attempt()
    }, { once: true })

    // 与 ChatView 同理：只赋值 src 不 load() 可能永远不加载；
    // load() 之后 readyState 会回到 HAVE_NOTHING，必须等到有数据再 play()，
    // 否则 play() 会被浏览器静默拒绝（表现为「点了没声」）。
    // 带时间戳：试听样本可能被重新生成过，不破缓存会听到旧音色。
    const sep = url.includes('?') ? '&' : '?'
    el.src = `${url}${sep}_t=${Date.now()}`
    el.load()

    const deadline = Date.now() + 5000
    const waitForData = () => {
      if (token !== testPlayToken || settled) return
      if (el.readyState >= 2 /* HAVE_CURRENT_DATA */) {
        el.play()?.catch((error: unknown) => {
          console.warn('[试听] 播放被拦截: ', error)
          ElMessage.warning('浏览器拦截了自动播放，点击页面任意位置后再试一次')
        })
        return
      }
      if (Date.now() >= deadline) {
        console.warn(`[试听] 等待数据超时: readyState=${el.readyState} src=${el.src}`)
        return
      }
      window.setTimeout(waitForData, 150)
    }
    window.setTimeout(waitForData, 150)
  }

  attempt()
}


const clickAudio = () => {
  play()
};

// ----------------------------------------------------------------------------
// 创建新角色：弹窗 + 表单 + 保存
// ----------------------------------------------------------------------------

const createRoleVisible = ref(false)

// 新角色表单：角色名称、性格特征（字符串）、音色（下拉 id）、形象描述（可空）
const newRole = reactive({
  name: '',
  personality: '',
  voiceId: '',
  imageDescription: '',
})

// 打开弹窗时重置表单
const openCreateRole = () => {
  newRole.name = ''
  newRole.personality = ''
  newRole.voiceId = ''
  newRole.imageDescription = ''
  generatedImages.value = []
  selectedImage.value = null
  generatingImage.value = false
  createRoleVisible.value = true
}

// --------------------------------------------------------------------------
// 候选形象：生成到后端 pictures/temp，用户点图片在已生成的形象间挑选
// --------------------------------------------------------------------------
interface GeneratedImage {
  index: number
  filename: string
  url: string        // 后端 /static 路径
  description: string // 选中这张时随角色一起保存的形象描述
}

const generatedImages = ref<GeneratedImage[]>([])
const selectedImage = ref<GeneratedImage | null>(null)
const generatingImage = ref(false)

// 展示用地址：经后端静态服务，带时间戳破浏览器缓存
const displayedImageUrl = computed(() =>
  selectedImage.value ? staticUrl(selectedImage.value.url) : ''
)

const selectGeneratedImage = (item: GeneratedImage) => {
  selectedImage.value = item
}

// 生成形象：用户填了描述就扩写，没填就让模型按 角色名+性格+音色 想象
const generateImage = async () => {
  const name = newRole.name.trim()
  if (!name) {
    ElMessage.warning('请先填写角色名称')
    return
  }
  generatingImage.value = true
  try {
    const resp = await fetch(`${API_BASE}/api/roles/generate-image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roleName: name,
        personality: newRole.personality.trim(),
        description: newRole.imageDescription.trim(),
        voiceId: newRole.voiceId,
      }),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(detail.detail || `HTTP ${resp.status}`)
    }
    const data = await resp.json()
    const item: GeneratedImage = {
      index: data.index,
      filename: data.filename,
      url: data.url,
      description: data.description || '',
    }
    generatedImages.value.push(item)
    selectedImage.value = item
    ElMessage.success('形象已生成，可继续生成其它方案')
  } catch (err) {
    console.warn('[生成形象] 失败：', err)
    ElMessage.warning(`生成形象失败：${err instanceof Error ? err.message : err}`)
  } finally {
    generatingImage.value = false
  }
}

// 创建进度的轮询器是全局单例（见 utils/roleCreation.ts）：
// 页面刷新后 localStorage 里残留的「创建中」角色也要能被继续盯住，
// 不能把轮询器锁死在弹窗组件里。这里只负责卸载时清掉自己那批定时器。
// 最近一次发起创建的角色名：轮询结束时的提示语要用（回调里拿不到角色名）
const lastCreatedRole = ref('')

onBeforeUnmount(() => {
  stopWatchingAll()
})

const handleCreationDone = (ok: boolean, error?: string) => {
  if (ok) {
    ElMessage.success(`角色「${lastCreatedRole.value}」创建完成，可以开始对话了`)
  } else {
    ElMessage.error(`角色「${lastCreatedRole.value}」创建失败：${error || '未知错误'}`)
  }
}

// 保存新角色：校验 -> 前端立即可用（角色列表 + 详情）-> 通知后端异步定稿
const saveNewRole = async () => {
  const name = newRole.name.trim()
  const personality = newRole.personality.trim()

  if (!name) {
    ElMessage.warning('请填写角色名称')
    return
  }
  if (!personality) {
    ElMessage.warning('请填写角色性格特征')
    return
  }
  // 重名检查：默认角色 + 已创建的自定义角色（大小写不敏感）
  const dup = roleOptions.value.some(
    r => r.value.toLowerCase() === name.toLowerCase()
  )
  if (dup) {
    ElMessage.warning(`角色「${name}」已存在，请换一个名称`)
    return
  }
  // 生成过形象就必须挑一张，否则后端不知道该保留哪张、该删哪些
  if (generatedImages.value.length > 0 && !selectedImage.value) {
    ElMessage.warning('请在已生成的形象中选择一张')
    return
  }

  // 1) 立即在前端可用：加入角色选择列表 + 保存详情
  settingsStore.addNewRole({ label: name, value: name, type: '虚拟角色' })
  const detail: CustomRoleDetail = {
    personality,
    voiceId: newRole.voiceId,
    imageDescription: selectedImage.value?.description || newRole.imageDescription.trim(),
  }
  settingsStore.setCustomRoleDetail(name, detail)

  // 2) 标记「创建中」：左下角出现滚动加载条，期间调用会被拦截
  settingsStore.addCreatingRole(name)

  // 3) 通知后端异步定稿（落盘 + 7 张情绪图 + 语音），前端不等它
  try {
    const resp = await fetch(`${API_BASE}/api/roles/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roleName: name,
        personality,
        description: detail.imageDescription,
        voiceId: newRole.voiceId,
        selectedImage: selectedImage.value?.filename || '',
      }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  } catch (err) {
    console.warn('[创建角色] 后端定稿接口调用失败：', err)
    settingsStore.removeCreatingRole(name)
    ElMessage.error('角色创建失败，请确认后端已启动')
    return
  }

  ElMessage.success(`角色「${name}」创建中，完成后即可使用`)
  createRoleVisible.value = false
  lastCreatedRole.value = name
  watchRoleCreation(name, handleCreationDone)
}

// 只有「创建新角色」产生的自定义角色可删；内置角色后端也会拒绝（403），
// 前端直接隐藏入口，免得点了才知道不能删。
const canDeleteRole = computed(() =>
  settingsStore.customRoles.some(r => r.value === settings.RoleConfig.roleName)
)
const deletingRole = ref(false)

// 删除角色：先二次确认，再由后端清落盘（角色信息 / 图片 / 语音 / Records / 音色登记），
// **成功之后**才清前端状态。顺序不能反 —— 反过来一旦后端失败，前端已经查不到这个角色，
// 用户既看不见它、也没法重试。
const deleteCurrentRole = async () => {
  const name = settings.RoleConfig.roleName
  if (!canDeleteRole.value || !name) return
  try {
    await ElMessageBox.confirm(
      `将删除角色「${name}」的全部记录：角色设定、形象与情绪图片、语音、对话记录（Records）与后端音色登记。此操作不可撤销。`,
      '删除角色',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  deletingRole.value = true
  try {
    const resp = await fetch(`${API_BASE}/api/roles/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roleName: name }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
    settingsStore.purgeRole(name)
    const count = Array.isArray(data.removed) ? data.removed.length : 0
    ElMessage.success(
      count
        ? `角色「${name}」已删除（清理 ${count} 项落盘记录）`
        : `角色「${name}」已移除（后端没有找到它的落盘记录）`
    )
  } catch (err) {
    console.warn('[删除角色] 失败：', err)
    ElMessage.error(`删除角色失败：${err instanceof Error ? err.message : err}`)
  } finally {
    deletingRole.value = false
  }
}

// 试听选中音色：拉取后端为该音色预生成的样本（本地还没有就现场合成一份）。
const previewAudioEl = ref<HTMLAudioElement | null>(null)
let previewToken = 0
// 上一次试听创建的 blob URL，换音色时释放，避免一直占着内存
let previewObjectUrl: string | null = null

const releasePreviewUrl = () => {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = null
  }
}

const previewVoice = async () => {
  const voiceId = newRole.voiceId
  if (!voiceId) {
    ElMessage.warning('请先选择音色')
    return
  }
  const el = previewAudioEl.value
  if (!el) {
    // 音频元素在弹窗里，理论上打开弹窗后一定存在；真拿不到就别静默失联
    console.warn('[试听] 未找到音频元素（弹窗未渲染？）')
    ElMessage.warning('试听组件未就绪，请重新打开弹窗')
    return
  }

  // 抢占全局发声通道，避免与对话语音/其它试听叠在一起
  claimPlayback(el)
  const token = ++previewToken

  // 播放就绪后起播。readyState>=2 才 play()：在 0 时发起会被浏览器挂住很久，
  // 落定时早已是过期请求（项目里踩过这个坑，见 MEMORY 的音频五条铁律）。
  // onTimeout 由调用方决定「等不到数据」时怎么办。
  const playWhenReady = (sourceLabel: string, onTimeout: () => void) => {
    const deadline = Date.now() + 5000
    const waitForData = () => {
      if (token !== previewToken) return
      if (el.readyState >= 2 /* HAVE_CURRENT_DATA */) {
        el.play()?.catch((error: unknown) => {
          console.warn(`[试听] play() 被拒绝（${sourceLabel}）:`, error)
          ElMessage.warning('浏览器拦截了自动播放，点击页面任意位置后再试')
        })
        return
      }
      if (Date.now() >= deadline) {
        console.warn(
          `[试听] 等待音频数据超时（${sourceLabel}）readyState=${el.readyState} ` +
          `networkState=${el.networkState} src=${el.currentSrc || el.src}`
        )
        onTimeout()
        return
      }
      window.setTimeout(waitForData, 150)
    }
    window.setTimeout(waitForData, 150)
  }

  // blob 链路走不通时的兜底：直连后端地址。http(s) URL 可以安全带 _t 破缓存。
  const fallbackToDirect = () => {
    if (token !== previewToken) return
    console.warn('[试听] blob 地址加载不出数据，回退到直连地址重试')
    releasePreviewUrl()
    el.src = `${API_BASE}/api/voices/preview?voice=${encodeURIComponent(voiceId)}&_t=${Date.now()}`
    el.load()
    playWhenReady('direct', () => {
      console.warn('[试听] 直连地址同样超时')
      ElMessage.warning('试听音频加载超时，请确认后端已启动')
    })
  }

  try {
    const resp = await fetch(`${API_BASE}/api/voices/preview?voice=${encodeURIComponent(voiceId)}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    if (!blob.size) throw new Error('返回的音频为空')

    if (token !== previewToken) return

    // 关键：blob URL 本身就是「每次 fetch 都不同」的，**不能**再拼 ?_t= 时间戳。
    // 往 blob: URL 后面加查询串会改变 URL 串，浏览器按整串查不到 blob 条目，
    // 元素永远加载不出来（readyState 停在 0、无 error、只有静默超时）。
    // 破缓存这套只对 http(s) URL 有意义。
    releasePreviewUrl()
    previewObjectUrl = URL.createObjectURL(blob)
    el.src = previewObjectUrl
    el.load()
    playWhenReady('blob', fallbackToDirect)
  } catch (err) {
    // 走到这里说明「样本没拿到」而不是「拿到了放不出来」，直连也一样没资源，
    // 所以不做兜底，直接把原因说清楚。
    console.warn('[试听] 音色样本获取失败：', err)
    ElMessage.warning('试听失败：未能从后端取到音色样本，请确认后端已启动')
  }
}

// 音频元素被替换/卸载时释放 blob URL
onBeforeUnmount(() => {
  releasePreviewUrl()
})


// const formatTime = (seconds: number) => {
//   const mins = Math.floor(seconds/60)
//   const secs = Math.floor(seconds%60)
//   return `${mins}:${secs.toString().padStrat(2, '0')}`
// }
//
//
// const audioElement = ref<HTMLAudioElement | null>(null)
// const isPlaying = ref(false)
// const currentTime = ref(0)
// const duration = ref(0)
//
// const audioUrl = computed(() => getAudioUrl(settings.RoleConfig.roleName))
//
// const togglePlay = () => {
//   if (isPlaying.value) {
//     audioElement.value.pause()
//   } else {
//     audioElement.value.play()
//   }
//
//   isPlaying.value = !isPlaying.value
// }
//
// const handleTimeUpdate = (e) => {
//   currentTime.value = e.target.currentTime
// }
//
// const hanldeLoadedMetadata = (e) => {
//   duration.value = e.target.durtion
// }
//
// watch (isPlaying, (newVal) => {
//   if (!audioElement.value) return
//
//   if (newVal) {
//     audioElement.value.play()
//   } else {
//     audioElement.value.pause()
//   }
// })

</script>

<template>
  <!-- 设置抽屉组件，用于展示和编辑应用设置 -->
  <el-drawer style="background-color: var(--bg-color);" v-model="visible" title="设置" direction="rtl" size="380px">
    <div class="settings-container">
      <!-- 运行时模式开关：置于设置页最顶部，按钮沿用「创建新角色」的样式 -->
      <div class="app-mode-bar" :class="{ 'is-mock': isMockMode }">
        <div class="app-mode-status">
          <span class="app-mode-dot" />
          当前：{{ appModeLabel }}
        </div>
        <div class="app-mode-tip">
          {{ isMockMode
              ? 'AI 已旁路：回复固定为系统状态回执，音频用本地测试样本，图像固定为 neutral。用于验证前端展示、后端处理与前后端连接。'
              : 'AI 已接入：所有基础功能可用。切换后立即生效，无需刷新页面。' }}
        </div>
        <button
            type="button"
            class="create-role-btn app-mode-btn"
            :class="{ 'is-mock': isMockMode }"
            :disabled="modeSwitching"
            @click="toggleAppMode"
        >
          {{ modeSwitching ? '切换中…' : (isMockMode ? '切换回正式版' : '切换到 Mock 版') }}
        </button>
      </div>

      <!-- 使用element-plus的表单组件来展示和编辑设置 -->
      <el-form :model="settings" label-width="120px">
        <!-- 深色模式切换 -->
        <el-form-item label="深色模式">
          <el-switch v-model="settings.isDarkMode" @change="handleDarkModeChange" />
        </el-form-item>

        <!-- 模型选择 -->
        <el-form-item label="文本模型">
          <div class="model-selection">
            <el-select
              v-model="settings.modelText"
              class="w-full"
              :popper-class="'model-select-dropdown'"
            >
              <el-option
                v-for="model in plainModelType"
                :key="model.value"
                :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag 
                      size="small" 
                      :type="getModelTagType(model.type)"
                      class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
          <div class="add-model-button">
            <el-button type="primary" link @click="showAddModelDialog">
              <el-icon><Plus /></el-icon>
              添加模型
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="语音模型">
          <div class="model-selection">
            <el-select
                v-model="settings.modelVoice"
                class="w-full"
                :popper-class="'model-select-dropdown'"
            >
              <el-option
                  v-for="model in voiceModelType"
                  :key="model.value"
                  :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                  :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag
                        size="small"
                        :type="getModelTagType(model.type)"
                        class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
        </el-form-item>

        <el-form-item label="图像模型">
          <div class="model-selection">
            <el-select
                v-model="settings.modelImage"
                class="w-full"
                :popper-class="'model-select-dropdown'"
            >
              <el-option
                  v-for="model in text2picModelType"
                  :key="model.value"
                  :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                  :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag
                        size="small"
                        :type="getModelTagType(model.type)"
                        class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
        </el-form-item>

        <el-form-item label="角色选择">
          <div class="select-box">
          <span class="label">
            <!---这一行span可能可以删掉--->
          <el-select
              :model-value="settingsStore.RoleConfig.roleName"
              @update:model-value="onRoleChange"
              placeholder="请选择角色"
              class="w-full"
              :popper-class="'model-select-dropdown'"
          >
            <el-option
                v-for="role in roleOptions"
                :key="role.value"
                :label="`${(role.type)} | ${role.label}`"
                :value="role.value"
            >

              <div class="role-option">
                <div class="role-info">
                  <el-tag
                      size="samll"
                      :type="getRoleTagType(role.type)"
                      class="role-type-tag"
                  >
                    {{ role.type }}
                  </el-tag>
                  <span>{{ role.label }}</span>
                </div>
                <!---删除入口不放在下拉项里：点选项会同时触发选中，容易误删正在切换的角色。
                    自定义角色的删除按钮统一放在角色选择框下方（.delete-role-btn）。--->
              </div>
            </el-option>
          </el-select>
          </span>
          </div>
          <button
              v-if="canDeleteRole"
              type="button"
              class="delete-role-btn"
              :disabled="deletingRole"
              @click="deleteCurrentRole"
          >
            {{ deletingRole ? '正在删除…' : '删除该角色' }}
          </button>
        </el-form-item>


        <div class="function-box document-viewer">
          <div class="scroll-container">
            <div v-if="!content && errorMessage" class="loading">选择角色查看文档</div>

            <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

            <pre v-else class="content">{{ content }}</pre>
          </div>
        </div>


        <div class="function-box avatar-box">
          <img
              :src="roleImageUrl"
              alt="角色形象"
              class="role-avatar"
              @error="handleImageError"
          >
          <div v-if="!roleImageUrl" class="avatar-placeholder">
            显示失败
            <i class="el-icon-picture-outline"></i>
          </div>
        </div>

        <div>这个角色在向你打招呼</div>
        <div class="voice-label">音色：{{ currentVoiceLabel }}</div>
        <audio ref="audio" preload="auto" />

        <el-button class="play-button"
        @click="clickAudio()"
        >▶</el-button>

        <!-- LLM/VLM设置 -->
        <template v-if="showLLMSettings">
          <el-divider>模型参数</el-divider>
          <!-- Temperature设置-->

          <!-- API Key输入 -->
          <el-form-item label="API Key">
            <el-input v-model="settings.apiKey" type="password" show-password placeholder="请输入API Key" />
          </el-form-item>

          <el-form-item label="Temperature">
            <el-slider v-model="settings.temperature" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
          <!-- 最大Token设置 -->
          <el-form-item label="最大Token">
            <el-input-number v-model="settings.maxTokens" :min="1" :max="4096" :step="1" />
          </el-form-item>
          <!-- 流式响应 -->
          <el-form-item>
            <template #label>
              流式响应
              <el-tooltip content="开启将后将实时显示AI回复" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-switch v-model="settings.streamResponse" />
          </el-form-item>
          <!-- Top P设置 -->
          <el-form-item label="Top P">
            <el-slider v-model="settings.topP" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
          <!-- Top K设置 -->
          <el-form-item label="Top K">
            <el-input-number v-model="settings.topK" :min="1" :max="100" :step="1" />
          </el-form-item>
          <!-- Frequency Penalty -->
          <el-form-item>
            <template #label>
              重复惩罚
              <el-tooltip content="控制模型重复使用相同词语的倾向，值越大越不倾向重复" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-slider 
              v-model="settings.frequencyPenalty" 
              :min="-2" 
              :max="2" 
              :step="0.1" 
              show-input
            />
          </el-form-item>
        </template>

        <!-- 文生图设置 -->
        <template v-if="showT2ISettings">
          <el-divider>文生图模型参数</el-divider>
          
          <el-form-item label="图片尺寸">
            <el-select
              v-model="settings.t2iConfig.imageSize"
              class="w-full"
            >
              <el-option
                v-for="option in imageSizeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item>
            <template #label>
              推理步数
              <el-tooltip content="控制生成图像的精细程度，值越大生成图像越精细" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-slider
              v-model="settings.t2iConfig.inferenceSteps"
              :min="10"
              :max="50"
              :step="1"
              show-input
            />
          </el-form-item>
        </template>
      </el-form>



      <!-- 保存设置按钮 -->
      <div class="settings-footer">
        <el-button type="primary" @click="handleSave">保存设置</el-button>
      </div>

      <!-- 创建新角色：位于设置最底部，居中，绿底白字 -->
      <div class="create-role-bar">
        <button type="button" class="create-role-btn" @click="openCreateRole">
          + 创建新角色
        </button>
      </div>
    </div>

    <!-- 添加/编辑模型对话框 -->
    <el-dialog
      :title="isEditing ? '编辑模型' : '添加模型'"
      v-model="modelDialogVisible"
      width="500px"
    >
      <el-form :model="currentModelText" label-width="100px">
        <el-form-item label="模型名称">
          <el-input v-model="currentTextModel.label" placeholder="请输入模型名称(DS-R1)" />
        </el-form-item>
        <el-form-item label="模型标识">
          <el-input v-model="currentTextModel.value" placeholder="请输入模型标识(deepseek-ai/DeepSeek-R1)" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-select v-model="currentTextModel.type">
            <el-option label="普通对话" value="plain" />
            <el-option label="视觉模型" value="visual" />
            <el-option label="文生图" value="text2img" />
            <el-option label="语音" value="voice"/>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveModel">确定</el-button>
      </template>
    </el-dialog>

    <!-- 创建新角色弹窗 -->
    <el-dialog
      title="创建新角色"
      v-model="createRoleVisible"
      width="560px"
      align-center
      :close-on-click-modal="false"
    >
      <div class="create-role-form">
        <!-- 1. 角色名称（必填，最上方） -->
        <div class="cr-field">
          <label class="cr-label">角色名称 <span class="cr-required">*</span></label>
          <el-input
            v-model="newRole.name"
            placeholder="例如：星野"
            maxlength="20"
            show-word-limit
          />
        </div>

        <!-- 2. 角色性格特征（必填，纵向排列在名称下方） -->
        <div class="cr-field">
          <label class="cr-label">角色性格特征 <span class="cr-required">*</span></label>
          <el-input
            v-model="newRole.personality"
            type="textarea"
            :rows="4"
            placeholder="描述角色的性格、语气、口头禅等，将作为该角色的设定文档保存"
          />
        </div>

        <!-- 3. 音色设置：按类别分组下拉 + 试听 -->
        <div class="cr-field">
          <label class="cr-label">音色设置</label>
          <div class="cr-voice-row">
            <el-select
              v-model="newRole.voiceId"
              placeholder="请选择音色"
              class="cr-voice-select"
            >
              <el-option-group
                v-for="group in VOICE_CATEGORY_GROUPS"
                :key="group.category"
                :label="group.category"
              >
                <el-option
                  v-for="v in group.voices"
                  :key="v.id"
                  :label="`${v.name}（${v.gender} · ${v.desc}）`"
                  :value="v.id"
                />
              </el-option-group>
            </el-select>
            <el-button @click="previewVoice">试听</el-button>
          </div>
        </div>

        <!-- 4. 形象设置：描述输入框 + 居中圆角矩形展示框 + 生成按钮（可留空） -->
        <div class="cr-field cr-appearance">
          <label class="cr-label">形象设置（可选）</label>
          <el-input
            v-model="newRole.imageDescription"
            type="textarea"
            :rows="3"
            placeholder="填写对该角色形象的描述，例如：银发紫瞳的少女，身着深色制服……（可留空，由模型自行设计）"
          />

          <!-- 文本/图像模型工作期间的旋转加载条，位于图像框上方 -->
          <div v-if="generatingImage" class="cr-generating">
            <span class="cr-spinner" />
            <span>正在生成形象…</span>
          </div>

          <!-- 形象框：点击弹出下拉，在已生成的形象之间检索 -->
          <el-dropdown trigger="click" placement="bottom" @command="selectGeneratedImage">
            <div class="cr-avatar-box">
              <img
                v-if="displayedImageUrl"
                :src="displayedImageUrl"
                alt="角色形象"
                class="cr-avatar-img"
              >
              <div v-else-if="newRole.name" class="cr-avatar-placeholder">
                {{ newRole.name.charAt(0) }}
              </div>
              <div v-else class="cr-avatar-empty">形象预览</div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="item in generatedImages"
                  :key="item.filename"
                  :command="item"
                >
                  <div class="cr-thumb-row">
                    <img :src="staticUrl(item.url)" class="cr-thumb" alt="">
                    <span>形象 {{ item.index + 1 }}</span>
                  </div>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <div v-if="generatedImages.length" class="cr-image-hint">
            已生成 {{ generatedImages.length }} 张，点击图片可切换
            （当前：第 {{ (selectedImage?.index ?? 0) + 1 }} 张）
          </div>

          <button type="button" class="create-role-btn cr-generate-btn" :disabled="generatingImage" @click="generateImage">
            {{ generatingImage ? '生成中…' : '生成形象' }}
          </button>
        </div>
      </div>

      <template #footer>
        <el-button @click="createRoleVisible = false">取消</el-button>
        <el-button type="success" @click="saveNewRole">创建角色</el-button>
      </template>

      <!-- 试听专用音频元素，独立于设置面板的试听，避免互相打断 -->
      <audio ref="previewAudioEl" preload="none" />
    </el-dialog>
  </el-drawer>
</template>

<style lang="scss" scoped>
:deep(.model-select-dropdown) {
  .el-select-dropdown__item {
    padding: 0 12px;
  }
}

// 设置页面样式
.settings-container {
  padding: 1rem;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

// 保存按钮布局
.settings-footer {
  margin-top: auto;
  padding-top: 1rem;
  text-align: right;
}

// 全宽样式，用于表单项
.w-full {
  width: 100%;
}

// 表单项提示样式
.form-item-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.model-selection {
  width: 100%;
}

.select-box {
  cursor: pointer;
  width: 100%;
}

.add-model-button {
  margin-top: 8px;
}

.model-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.role-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.model-actions {
  display: flex;
  gap: 4px;
}

.info-icon {
  margin-left: 4px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
}


.model-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.role-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-type-tag {
  font-size: 12px;
  padding: 0 4px;
  height: 20px;
  line-height: 18px;
}

.role-type-tag {
  font-size: 12px;
  padding: 0 4px;
  height: 20px;
  line-height: 18px;
}

.function-box {
  background: white;
  border-radius: 12px;
  padding: 15px;
  box-shadow: 0 2px 4px 0 rgba(0,0,0,0.1);
}

.document-viewer {
  flex: 1;
  max-width: 400px;
}

.scroll-container {
  height:300px;
  overflow-y: auto;
  background: #fafafa;
  border-radius: 6px;
  padding: 10px;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 1em;
  font-weight: bolder;
}

.avatar-box {
  width: 250px;
  height: 250px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

.role-avatar {
  width: 100%;
  height:100%;
  object-fit: cover;
  border-radius: 8px;
}

.avatar-placeholder {
  font-size: 40px;
  color: #ddd;
}

.audio-control {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}

.voice-label {
  margin: 4px 0 8px;
  font-size: 12px;
  opacity: 0.7;
}

.play-button {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: #646cff;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;
}

.play-button:hover {
  background: #90caf9;
}

.time-display {
  font-family: monospace;
  color: #1a1a1a;
}

// 创建新角色：设置页最底部，居中
.create-role-bar {
  margin-top: 1rem;
  padding-top: 1rem;
  display: flex;
  justify-content: center;
}

// 绿底白字，色差保证可读（深绿 #357a35 对白字约 5.3:1），圆角 + 柔阴影观感偏柔和
.create-role-btn {
  width: 80%;
  max-width: 320px;
  padding: 10px 0;
  border: none;
  border-radius: 10px;
  background-color: #357a35;
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(53, 122, 53, 0.28);
  transition: background-color 0.25s ease, box-shadow 0.25s ease, transform 0.1s ease;
}

.create-role-btn:hover {
  background-color: #3f8c3f;
  box-shadow: 0 4px 12px rgba(53, 122, 53, 0.34);
}

.create-role-btn:active {
  transform: translateY(1px);
}

// 删除角色：描边红字，刻意不与「创建新角色」的实心绿同权重 ——
// 破坏性操作不该长得像主操作按钮。定义在 .create-role-btn 之后，
// 同优先级下后定义者生效（width 不会被它的 80% 反向覆盖）。
.delete-role-btn {
  margin-top: 10px;
  width: 80%;
  max-width: 320px;
  padding: 8px 0;
  border: 1px solid #b23b3b;
  border-radius: 10px;
  background-color: transparent;
  color: #b23b3b;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 1px;
  cursor: pointer;
  transition: background-color 0.25s ease, color 0.25s ease;
}

.delete-role-btn:hover:not(:disabled) {
  background-color: #b23b3b;
  color: #ffffff;
}

.delete-role-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

// 弹窗表单
.create-role-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.cr-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

// 形象区整体居中（图像框、提示、按钮都在中轴线上）
.cr-appearance {
  align-items: center;
}

// 旋转加载条：位于图像框上方
.cr-generating {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.cr-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--el-border-color);
  border-top-color: #357a35;
  border-radius: 50%;
  animation: cr-spin 0.8s linear infinite;
}

@keyframes cr-spin {
  to { transform: rotate(360deg); }
}

.cr-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.cr-required {
  color: #f56c6c;
  margin-left: 2px;
}

.cr-voice-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cr-voice-select {
  flex: 1;
}

// 形象展示框：圆角矩形，与聊天主页角色图展示风格一致
.cr-avatar-box {
  margin-top: 10px;
  width: 180px;
  height: 180px;
  border-radius: 16px;
  border: 2px dashed var(--el-border-color);
  background: var(--el-fill-color-light);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: pointer;
}

.cr-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cr-image-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.cr-generate-btn {
  margin-top: 12px;
  width: 60%;
  max-width: 220px;
}

.cr-generate-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.cr-thumb-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cr-thumb {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  object-fit: cover;
}

.cr-avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 64px;
  font-weight: 700;
  color: var(--el-color-primary);
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.12), rgba(64, 158, 255, 0.04));
}

.cr-avatar-empty {
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

// ----------------------------------------------------------------------------
// 运行时模式开关
//
// 必须定义在 .create-role-btn 之后：按钮复用那套绿底白字，同优先级下后定义者
// 生效，放前面的话 width 会被 .create-role-btn 的 80% 覆盖回去。
// ----------------------------------------------------------------------------
.app-mode-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid rgba(53, 122, 53, 0.35);
  background: rgba(53, 122, 53, 0.08);
  transition: border-color 0.25s ease, background-color 0.25s ease;
}

// Mock 态换成琥珀色：一眼能看出「当前不是正常链路」
.app-mode-bar.is-mock {
  border-color: rgba(196, 125, 26, 0.45);
  background: rgba(196, 125, 26, 0.12);
}

.app-mode-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.app-mode-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #357a35;
}

.app-mode-bar.is-mock .app-mode-dot {
  background: #c47d1a;
}

.app-mode-tip {
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
  color: var(--el-text-color-secondary);
}

.app-mode-btn {
  width: 100%;
  max-width: 320px;
}

.app-mode-btn.is-mock {
  background-color: #9a5b12;
  box-shadow: 0 2px 8px rgba(154, 91, 18, 0.32);
}

.app-mode-btn.is-mock:hover {
  background-color: #b06d1f;
  box-shadow: 0 4px 12px rgba(154, 91, 18, 0.38);
}

.app-mode-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

</style>