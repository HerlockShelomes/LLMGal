import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// 定义模型选项类型
export interface ModelOption {
    label: string
    value: string
    // 大模型类型：可选普通对话模型，视觉输入，文生图模型
    type: 'plain' | 'visual' | 'text2img' | 'voice'
}

export interface RoleOption {
    label: string
    value: string
    type: '虚拟角色' | '数字分身'
}

// 静态资源解析：new URL('/src/assets/...', import.meta.url) 以 / 开头，
// 生产构建下不会被 Vite 重写，路径直接失效。改用 import.meta.glob 在构建期收集资源，
// 拿到的是经过 hash 处理的真实 URL，dev / build 都可用。
const pictureModules = import.meta.glob('/src/assets/pictures/**/*.{jpg,jpeg,png}', {
    eager: true,
    query: '?url',
    import: 'default',
}) as Record<string, string>

// 语音：火山返回 mp3、阿里 Qwen3-TTS 返回 wav，两种都要能取到。
// 新生成的优先 wav，取不到再回退 mp3（历史素材仍是 mp3）。
const voiceWavModules = import.meta.glob('/src/assets/voice/**/*.wav', {
    eager: true,
    query: '?url',
    import: 'default',
}) as Record<string, string>

const voiceMp3Modules = import.meta.glob('/src/assets/voice/**/*.mp3', {
    eager: true,
    query: '?url',
    import: 'default',
}) as Record<string, string>

const roleDocModules = import.meta.glob('/src/assets/roles/*.txt', {
    eager: true,
    query: '?url',
    import: 'default',
}) as Record<string, string>

const ASSET_ROOT = '/src/assets/'

// 资源缺失时返回空串，交由调用方判断，避免抛异常打断渲染
const resolveAsset = (modules: Record<string, string>, path: string): string =>
    modules[path] ?? ''

export const getImageUrl = (name: string, index: string) => {
    return resolveAsset(pictureModules, `${ASSET_ROOT}pictures/${name}/${name}_${index}.jpg`)
}

export const getDescriptionFile = (name: string) => {
    return resolveAsset(roleDocModules, `${ASSET_ROOT}roles/${name}.txt`)
}

// 去重，避免 dev 直连路径与 glob 解析结果相同时重复请求
const dedupe = (urls: string[]): string[] => [...new Set(urls.filter(Boolean))]

/**
 * 角色本轮对话语音的候选地址，按优先级排列。
 *
 * dev 下必须把「直连磁盘路径」放在第一位：后端每一轮都会覆盖写
 * frontend/src/assets/voice/{role}/{role}_{index}_Stream.wav，
 * 而 import.meta.glob 是**构建期快照**，收不到这一轮新写的文件，
 * 于是会回退到同名的历史 mp3 —— 用户听到的就是上一轮的旧语音（内容对不上）。
 * 直连路径拿不到时（例如该 provider 产出的是 mp3），由调用方按 error 事件回退。
 *
 * 生产构建下新增文件本就不该写进 src，只走 glob；返回空数组表示无资源可用。
 */
export const getAudioUrls = (roleName: string, index: string): string[] => {
  const base = `${ASSET_ROOT}voice/${roleName}/${roleName}_${index}_Stream`
  const globbed = [
    resolveAsset(voiceWavModules, `${base}.wav`),
    resolveAsset(voiceMp3Modules, `${base}.mp3`),
  ]
  if (import.meta.env.DEV) {
    // 直连磁盘的 wav 与 mp3 都放进来：qwen 档产 wav、火山档产 mp3，
    // 少放一个的话另一半 provider 的新文件就永远取不到（只能听历史素材）。
    return dedupe([
      `/src/assets/voice/${roleName}/${roleName}_${index}_Stream.wav`,
      `/src/assets/voice/${roleName}/${roleName}_${index}_Stream.mp3`,
      ...globbed,
    ])
  }
  return dedupe(globbed)
}

export const getAudioUrl = (roleName: string, index: string) =>
  getAudioUrls(roleName, index)[0] ?? ''

/**
 * 设置面板试听音的候选地址。
 * 新的试听样本由 backend/generate_role_samples.py 生成，带 _Stream 后缀、
 * 且用的是该角色专属音色；找不到时再回退到手工放置的旧素材。
 */
export const getTestAudioUrls = (roleName: string): string[] => {
  const streamBase = `${ASSET_ROOT}voice/${roleName}/${roleName}_test_Stream`
  const legacyBase = `${ASSET_ROOT}voice/${roleName}/${roleName}_test`
  const globbed = [
    resolveAsset(voiceWavModules, `${streamBase}.wav`),
    resolveAsset(voiceMp3Modules, `${streamBase}.mp3`),
    resolveAsset(voiceWavModules, `${legacyBase}.wav`),
    resolveAsset(voiceMp3Modules, `${legacyBase}.mp3`),
  ]
  if (import.meta.env.DEV) {
    return dedupe([`/src/assets/voice/${roleName}/${roleName}_test_Stream.wav`, ...globbed])
  }
  return dedupe(globbed)
}

export const getTestAudioUrl = (roleName: string) =>
  getTestAudioUrls(roleName)[0] ?? ''

// 角色 -> 音色中文名，仅用于设置面板展示。
// 真正发声用的是 backend/config.py 的 ROLE_VOICES（可用 .env 覆盖），
// 改音色请改后端，这里同步改一下文案即可。
export const ROLE_VOICE_LABELS: Record<string, string> = {
  Wendy: 'Serena（苏瑶 · 温柔小姐姐）',
  Testificate: 'Momo（茉兔 · 撒娇搞怪）',
  Testificate_Boy: 'Ethan（晨煦 · 阳光温暖）',
  GirlProgrammer: 'Maia（四月 · 知性温柔）',
}

export const getFileContent = async (name: string) => {
    const errorMsg = ref<string>('')
    try {
        const response = await fetch(getDescriptionFile(name))

        if (response.ok) {
            return await response.text()
        }
    } catch (err) {
        errorMsg.value = `加载失败: ${err instanceof Error ? err.message : '未知错误'}`

        if (import.meta.env.DEV) {
            console.error('文件加载错误: ', err)
        }

    }
}

// 定义设置状态接口
interface SettingsState {
    isDarkMode: boolean
    temperature: number
    maxTokens: number
    modelText: string
    modelVoice: string
    modelImage: string
    apiKey: string
    streamResponse: boolean
    topP: number
    topK: number
    customModels: ModelOption[]
    frequencyPenalty: number
    // 添加文生图配置
    t2iConfig: {
        imageSize: string
        inferenceSteps: number
    }
    RoleConfig: {
        roleName: string
        roleDescription: string
        roleImage: string
    }

    customRoles: RoleOption[]
}

// 定义一个名为 'settings' 的 store
export const useSettingsStore = defineStore('settings', {
    // 定义 store 的状态
    state: (): SettingsState => ({
        isDarkMode: false,
        temperature: 0.7,
        maxTokens: 1000,
        // 留空 = 跟随后端 .env 里的 TEXT_MODEL。
        // 原先写死 'deepseek-ai/DeepSeek-V3'（旧中转站 ID），后端 provider 是智谱时
        // 会被原样转发过去，直接 1211「模型不存在」，整轮对话失败。
        modelText: '',
        modelVoice: 'volcano_tts',
        modelImage: 'high_aes_general_v20_L',
        apiKey: '',
        streamResponse: true,
        topP: 0.7,
        topK: 50,
        customModels: [],
        frequencyPenalty: 0,
        // 初始化文生图配置
        t2iConfig: {
            imageSize: '1024x1024',
            inferenceSteps: 20
        },

        RoleConfig: {
            roleName: "Testificate",
            roleDescription: getDescriptionFile("Testificate"),
            roleImage: getImageUrl("Testificate", "neutral"),
        },
        customRoles: []
    }),

    // 定义 store 的动作
    actions: {
        toggleDarkMode(): void {
            this.isDarkMode = !this.isDarkMode
            // 根据当前的深色模式状态设置 HTML 元素的 data-theme 属性
            document.documentElement.setAttribute('data-theme', this.isDarkMode ? 'dark' : 'light')
        },

        updateSettings(settings: Partial<SettingsState>): void {
            // 使用 Object.assign 方法将传入的设置对象合并到当前 store 的状态中
            Object.assign(this.$state, settings)
        },

        addCustomModel(model: ModelOption): void {
            this.customModels.push(model)
        },

        addNewRole(role: RoleOption): void {
            this.customRoles.push(role)
        },

        removeCustomModel(value: string): void {
            const index = this.customModels.findIndex(m => m.value === value)
            if (index !== -1) {
                this.customModels.splice(index, 1)
            }
        },

        removeCustomRole(value: string): void {
            const index = this.customRoles.findIndex(r => r.value === value)
            if (index !== -1) {
                this.customRoles.splice(index, 1)
            }
        },

        editCustomModel(value: string, updatedModel: ModelOption): void {
            const index = this.customModels.findIndex(m => m.value === value)
            if (index !== -1) {
                this.customModels[index] = updatedModel
            }
        },

        editCustomRole(value: string, updatedRole: RoleOption): void {
            const index = this.customRoles.findIndex(r => r.value === value)
            if (index !== -1) {
                this.customRoles[index] = updatedRole
            }
        }
    },

    // 配置持久化选项
    persist: {
        // 存储键名
        key: 'ai-chat-settings',
        // 存储方式，这里使用的是 localStorage
        storage: localStorage,
        // localStorage 明文可读，任何 XSS 或共用电脑都能直接取走密钥，因此 apiKey 不落盘
        omit: ['apiKey'],
    },
})

// 将 modelOptions 改为 computed 属性
export const useModelOptions = () => {
    const store = useSettingsStore()
    return computed(() => [
        ...defaultModelOptions,
        ...store.customModels
    ])
}

export const useRoleOptions = () => {
    const store = useSettingsStore()
    return computed(() => [
        ...defaultRole,
        ...store.customRoles
    ])
}

export function useRoleAssets() {
    const roleImageUrl = ref<string>('')
    const fileContent = ref<string>('')

    const updateAssets = async (roleName: string) => {
        roleImageUrl.value = getImageUrl(roleName, 'neutral')

        try {
            const response = await fetch(getDescriptionFile(roleName))

            fileContent.value = await response.text()
        } catch (error) {
            console.error("文档加载失败", error)
        }

    }

    return {roleImageUrl, fileContent, updateAssets}
}

// 默认模型选项
// 注意：value 必须是后端 provider 真实存在的模型 ID，否则厂商会直接报「模型不存在」。
// 当前后端默认 provider 是智谱，实测可用 ID 见下方 GLM 系列；
// 第一项 value 为空 = 跟随后端 .env 的 TEXT_MODEL，最省心，建议保持。
export const defaultModelOptions: ModelOption[] = [
    { label: '跟随后端配置（推荐）', value: '', type: 'plain' },
    { label: 'GLM-5.3-Flash（智谱·免费档）', value: 'glm-5.3-flash', type: 'plain' },
    { label: 'GLM-5.3（智谱）', value: 'glm-5.3', type: 'plain' },
    { label: 'GLM-5.1（智谱）', value: 'glm-5.1', type: 'plain' },
    { label: 'GLM-4.7（智谱）', value: 'glm-4.7', type: 'plain' },
    { label: 'GLM-4.6（智谱）', value: 'glm-4.6', type: 'plain' },
    { label: 'GLM-4.5-Air（智谱）', value: 'glm-4.5-air', type: 'plain' },
    { label: 'FLUX.1-dev', value: 'black-forest-labs/FLUX.1-dev', type: 'text2img' },
    { label: 'Doubao-ImageGenerating', value: 'high_aes_general_v20_L', type: 'text2img' },
    { label: '图像特征保持（姿态可变）', value: 'high_aes_ip_v20', type: 'visual' },
    { label: '图像指令编辑（姿态固定）', value: 'byteedit_v2.0', type: 'visual' },
    { label: 'Volcano_VoiceGeneration', value: 'volcano_tts', type: 'voice'},
]

export const defaultRole: RoleOption[] = [
    { label: '温蒂', value: 'Wendy', type: '虚拟角色' },
    { label: '测试猫娘', value: 'Testificate', type: '虚拟角色' },
    { label: '开发者', value: 'Testificate_Boy', type: '数字分身' },
    { label: '开发的幻想', value: 'GirlProgrammer', type: '数字分身'},
]