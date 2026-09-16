import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

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

// 运行时模式：'prod' = 正式版（AI 接入）/ 'mock' = Mock 版（AI 旁路）。
// 唯一的真相源在后端（backend/runtime_mode.json，经 /api/system/mode 读写）：
// 这里的值只是给界面用的镜像，切换与同步一律以后端返回值为准。
export type AppMode = 'prod' | 'mock'

export const APP_MODE_LABELS: Record<AppMode, string> = {
    prod: '正式版（AI 已接入）',
    mock: 'Mock 版（AI 已旁路）',
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

// 后端 REST 地址。Vite dev 跑在 5173，后端在 8000，不写全地址会请求到 dev server 自己。
// 部署到别的机器时改前端 .env.local 的 VITE_API_BASE 即可。
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string) || 'http://127.0.0.1:8000'

// 后端把生成物（候选形象、音色样本、情绪图）挂在 /static 上，直接拼即可
export const staticUrl = (path: string): string => `${API_BASE}${path}`

const ASSET_ROOT = '/src/assets/'

// 资源缺失时返回空串，交由调用方判断，避免抛异常打断渲染
const resolveAsset = (modules: Record<string, string>, path: string): string =>
    modules[path] ?? ''

// 去重 + 丢弃空串，避免 dev 直连路径与 glob 解析结果相同时重复请求
const dedupe = (urls: string[]): string[] => [...new Set(urls.filter(Boolean))]

/**
 * 静态资源的候选地址，按优先级排列；全取不到时返回空数组。
 *
 * 为什么不能只查 import.meta.glob：它是**构建期快照**，收不到构建之后由后端
 * 运行时写入的文件。最典型的就是「创建新角色」刚生成的立绘与 7 张情绪图 ——
 * 内置角色在快照里能取到，新建角色必然取不到，于是图片直接显示失败。
 * 三级回退：
 *   ① 构建期 glob        内置角色，带 hash 的正式 URL
 *   ② dev 直连磁盘路径   后端就写在 frontend/src/assets 下，dev server 能直接服务
 *   ③ 后端 /static       dev/prod 通用兜底（路径由后端从自身文件位置推导）
 * 与 getAudioUrls 同一套思路：dev 下直连路径排在前，才能拿到刚写入的新文件。
 */
const assetCandidates = (
    modules: Record<string, string>,
    relPath: string,
): string[] => {
    const candidates = [resolveAsset(modules, `${ASSET_ROOT}${relPath}`)]
    if (import.meta.env.DEV) {
        candidates.push(`/src/assets/${relPath}`)
    }
    candidates.push(staticUrl(`/static/${relPath}`))
    return dedupe(candidates)
}

// 角色立绘：index 为情绪名（neutral/happy/...）或 original。候选全空 = 资源缺失。
export const getImageUrls = (name: string, index: string): string[] =>
    assetCandidates(pictureModules, `pictures/${name}/${name}_${index}.jpg`)

export const getImageUrl = (name: string, index: string): string =>
    getImageUrls(name, index)[0] ?? ''

// 角色设定文档（assets/roles/{角色}.txt）
export const getDescriptionFiles = (name: string): string[] =>
    assetCandidates(roleDocModules, `roles/${name}.txt`)

export const getDescriptionFile = (name: string): string =>
    getDescriptionFiles(name)[0] ?? ''

/**
 * 角色立绘的响应式地址 + 候选回退。
 *
 * 把 onError 接到 <img @error> 上：某个候选加载失败就自动试下一个，
 * 全部试完 url 变回空串，调用方据此显示占位符（沿用原有语义）。
 * 这样即便某个候选路径猜错（例如该情绪图确实没生成），也不会留下破图。
 *
 * 返回 { url, onError }。
 */
export function useRoleImage(name: () => string, index: () => string) {
    const candidates = ref<string[]>([])
    const cursor = ref(0)
    const url = computed(() => candidates.value[cursor.value] ?? '')

    // 角色或情绪一变就重新取候选列表，并从第一个重新试
    watch(
        () => [name(), index()] as const,
        () => {
            candidates.value = getImageUrls(name(), index())
            cursor.value = 0
        },
        { immediate: true },
    )

    const onError = () => {
        if (cursor.value < candidates.value.length) cursor.value += 1
    }

    return { url, onError }
}

/**
 * Mock 版音频的目录名：voice/_mock/{角色}/，与正式版的 voice/{角色}/ 并列。
 *
 * 两个目录彻底分开是有意的 —— Mock 版原先往正式版槽位写，留下两个问题：
 * ① 切回正式版后，引用同一 index 的历史消息会播到 Mock 拷进去的测试音频；
 * ② index 相同的两条消息（一条 mock、一条正式）指向同一个文件，事后无法区分。
 * 分开之后，用哪个目录由**这条消息自带的 mode** 决定（见 getAudioUrls 的 mode）。
 */
export const MOCK_VOICE_DIRNAME = '_mock'

/**
 * 角色本轮对话语音的候选地址，按优先级排列。
 *
 * mode 必须传「产出这条消息的模式」，不能传界面上的当前模式：
 * 响应在途时切模式、或回看历史消息时，用当前模式都会指到另一个目录。
 *
 * dev 下必须把「直连磁盘路径」放在第一位：后端每一轮都会覆盖写
 * frontend/src/assets/voice/{目录}/{role}_{index}_Stream.wav，
 * 而 import.meta.glob 是**构建期快照**，收不到这一轮新写的文件，
 * 于是会回退到同名的历史 mp3 —— 用户听到的就是上一轮的旧语音（内容对不上）。
 * 直连路径拿不到时（例如该 provider 产出的是 mp3），由调用方按 error 事件回退。
 *
 * 生产构建下新增文件本就不该写进 src，只走 glob；返回空数组表示无资源可用。
 */
export const getAudioUrls = (
  roleName: string,
  index: string,
  mode: AppMode = 'prod',
): string[] => {
  // 目录前缀只由模式决定，扩展名回退**只在同一个目录内**进行。
  // Mock 模式下刻意不回退到正式版目录：那里是真实对话音频，播出来只会让人
  // 误判成「mock 没生效」——宁可没有声音（后端已把 status 降为 partial）。
  const dir = mode === 'mock' ? `${MOCK_VOICE_DIRNAME}/${roleName}` : roleName
  const relBase = `voice/${dir}/${roleName}_${index}_Stream`
  const base = `${ASSET_ROOT}${relBase}`
  const globbed = [
    resolveAsset(voiceWavModules, `${base}.wav`),
    resolveAsset(voiceMp3Modules, `${base}.mp3`),
  ]
  if (import.meta.env.DEV) {
    // 直连磁盘的 wav 与 mp3 都放进来：qwen 档产 wav、火山档产 mp3，
    // 少放一个的话另一半 provider 的新文件就永远取不到（只能听历史素材）。
    return dedupe([
      `/src/assets/${relBase}.wav`,
      `/src/assets/${relBase}.mp3`,
      ...globbed,
    ])
  }
  return dedupe(globbed)
}

export const getAudioUrl = (roleName: string, index: string, mode: AppMode = 'prod') =>
  getAudioUrls(roleName, index, mode)[0] ?? ''

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

// 音色目录：按前端「创建新角色」弹窗的分类展示，id 直接是 Qwen3-TTS 的音色名，
// 便于后续后端联动时原样下发。分类按用户要求做简易区分（御姐/萝莉/雌小鬼/少年音等）。
export interface VoiceOption {
  id: string
  name: string
  gender: string
  desc: string
  category: string
}

export const VOICE_CATEGORY_GROUPS: { category: string; voices: VoiceOption[] }[] = [
  {
    category: '御姐',
    voices: [
      { id: 'Serena', name: '苏瑶', gender: '女', desc: '温柔小姐姐', category: '御姐' },
      { id: 'Katerina', name: '卡捷琳娜', gender: '女', desc: '御姐音色，韵律回味', category: '御姐' },
      { id: 'Maia', name: '四月', gender: '女', desc: '知性与温柔的碰撞', category: '御姐' },
      { id: 'Bellona', name: '燕铮莺', gender: '女', desc: '字正腔圆、热血铿锵', category: '御姐' },
      { id: 'Elias', name: '墨讲师', gender: '女', desc: '严谨又擅长叙事', category: '御姐' },
      { id: 'Jennifer', name: '詹妮弗', gender: '女', desc: '电影质感美语女声', category: '御姐' },
      { id: 'Seren', name: '小婉', gender: '女', desc: '温和舒缓的助眠女声', category: '御姐' },
    ],
  },
  {
    category: '萝莉',
    voices: [
      { id: 'Bella', name: '萌宝', gender: '女', desc: '喝酒不打醉拳的小萝莉', category: '萝莉' },
      { id: 'Bunny', name: '萌小姬', gender: '女', desc: '萌属性爆棚的小萝莉', category: '萝莉' },
      { id: 'Nini', name: '邻家妹妹', gender: '女', desc: '软糯黏人的甜嗓', category: '萝莉' },
      { id: 'Mia', name: '乖小妹', gender: '女', desc: '温顺如春水、乖巧如初雪', category: '萝莉' },
    ],
  },
  {
    category: '雌小鬼',
    voices: [
      { id: 'Vivian', name: '十三', gender: '女', desc: '拽拽的、可爱的小暴躁', category: '雌小鬼' },
      { id: 'Momo', name: '茉兔', gender: '女', desc: '撒娇搞怪，逗你开心', category: '雌小鬼' },
    ],
  },
  {
    category: '少年音',
    voices: [
      { id: 'Ethan', name: '晨煦', gender: '男', desc: '阳光温暖、活力朝气', category: '少年音' },
      { id: 'Moon', name: '月白', gender: '男', desc: '率性帅气', category: '少年音' },
      { id: 'Mochi', name: '沙小弥', gender: '男', desc: '聪明伶俐的小大人', category: '少年音' },
      { id: 'Nofish', name: '不吃鱼', gender: '男', desc: '不会翘舌音的设计师', category: '少年音' },
      { id: 'Aiden', name: '艾登', gender: '男', desc: '精通厨艺的美语大男孩', category: '少年音' },
      { id: 'Ryan', name: '甜茶', gender: '男', desc: '节奏拉满、戏感炸裂', category: '少年音' },
      { id: 'Pip', name: '顽屁小孩', gender: '男', desc: '调皮捣蛋、充满童真的小男孩', category: '少年音' },
    ],
  },
  {
    category: '成熟男声',
    voices: [
      { id: 'Neil', name: '阿闻', gender: '男', desc: '字正腔圆的新闻主播', category: '成熟男声' },
      { id: 'Eldric Sage', name: '沧明子', gender: '男', desc: '沉稳睿智的老者', category: '成熟男声' },
      { id: 'Vincent', name: '田叔', gender: '男', desc: '沙哑烟嗓，江湖气', category: '成熟男声' },
      { id: 'Kai', name: '凯', gender: '男', desc: '温润顺滑', category: '成熟男声' },
      { id: 'Arthur', name: '徐大爷', gender: '男', desc: '质朴沙哑的乡土老者，满村奇闻异事', category: '成熟男声' },
    ],
  },
  {
    category: '甜美小姐姐',
    voices: [
      { id: 'Cherry', name: '芊悦', gender: '女', desc: '阳光积极、亲切自然', category: '甜美小姐姐' },
      { id: 'Chelsie', name: '千雪', gender: '女', desc: '二次元虚拟女友', category: '甜美小姐姐' },
    ],
  },
]

// 扁平化列表，供按 id 反查中文名/描述（设置面板展示当前角色音色用）
export const VOICE_OPTIONS: VoiceOption[] = VOICE_CATEGORY_GROUPS.flatMap(g => g.voices)

// 自定义角色详情：前端「创建新角色」后立刻可用，持久化在 localStorage。
// 真正落盘到 src/assets/roles 与 pictures/Role_Description 由后端接口负责（见前端 persistRoleToDisk）。
export interface CustomRoleDetail {
  personality: string
  voiceId: string
  imageDescription: string
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
    // 自定义角色详情（音色/性格/形象描述），键为角色名，持久化在 localStorage，
    // 让「创建新角色」后角色在前端立即可用（详情不依赖后端落盘）。
    customRoleDetails: Record<string, CustomRoleDetail>
    // 正在后台创建中的角色（7 张情绪图 + 语音还没生成完）。
    // 这期间调用它会缺资源，前端据此拦截并提示「角色未创建完毕」。
    creatingRoles: string[]

    // 运行时模式的后端镜像（见 AppMode）。页面挂载与打开设置面板时从后端同步，
    // 不靠本地值推断，避免「手动改过后端开关文件但界面还显示旧状态」。
    appMode: AppMode
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
        customRoles: [],
        customRoleDetails: {},
        creatingRoles: [],
        appMode: 'prod'
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
        },

        // 保存/更新自定义角色详情（前端立即可用；真正写盘由后端接口完成）
        setCustomRoleDetail(roleName: string, detail: CustomRoleDetail): void {
            this.customRoleDetails[roleName] = { ...detail }
        },

        // 标记/取消「正在创建」的角色
        addCreatingRole(roleName: string): void {
            if (!this.creatingRoles.includes(roleName)) {
                this.creatingRoles.push(roleName)
            }
        },

        removeCreatingRole(roleName: string): void {
            this.creatingRoles = this.creatingRoles.filter(r => r !== roleName)
        },

        // 删除角色：前端状态一并清干净（后端落盘由 /api/roles/delete 负责）。
        // 删掉的正是当前选中角色时，回退到内置默认角色 —— 角色名是出图 / 音频 /
        // 人设的索引键，留在界面上只会指向一堆已经被删掉的文件。
        purgeRole(roleName: string): void {
            this.removeCustomRole(roleName)
            delete this.customRoleDetails[roleName]
            this.removeCreatingRole(roleName)
            if (this.RoleConfig.roleName !== roleName) return
            const fallback = defaultRole[0]
            this.RoleConfig.roleName = fallback.value
            this.RoleConfig.roleDescription = getDescriptionFile(fallback.value)
            this.RoleConfig.roleImage = getImageUrl(fallback.value, 'neutral')
        },

        // 写入后端同步回来的运行时模式（只做镜像，真正切换走 utils/appMode.ts）
        setAppMode(mode: AppMode): void {
            this.appMode = mode
        },
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

// 兜底角色：会话绑定的角色被删除时切到它。
// 写成字面量而不是从 defaultRole 里查，是为了避免模块初始化顺序带来的 TDZ
// （chat.ts 在模块顶层就 import 这两个常量）。
export const DEFAULT_ROLE_VALUE = 'Testificate'
export const DEFAULT_ROLE_LABEL = '测试猫娘'