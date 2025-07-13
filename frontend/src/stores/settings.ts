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

export const getImageUrl = (name: string, index: string) => {
    // 使用vite静态资源处理
    return new URL(`/src/assets/pictures/${name}/${name}_${index}.jpg`, import.meta.url).href
}

export const getDescriptionFile = (name: string) => {
    return new URL(`/src/assets/roles/${name}.txt`, import.meta.url).href
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
        modelText: 'deepseek-ai/DeepSeek-V3',
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
export const defaultModelOptions: ModelOption[] = [
    { label: 'DeepSeek-V3', value: 'deepseek-ai/DeepSeek-V3', type: 'plain' },
    { label: 'DeepSeek-R1', value: 'deepseek-ai/DeepSeek-R1', type: 'plain' },
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