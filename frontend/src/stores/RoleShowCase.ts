import { defineStore } from 'pinia'


// 定义设置状态接口
interface RoleShowCaseData {
    index: string
    emotion: string
}

// 定义一个名为 'settings' 的 store
export const useRSCstore = defineStore('RoleShow', {
    // 定义 store 的状态
    state: (): RoleShowCaseData => ({
        index: '0',
        emotion: 'neutral'
    }),

    // 定义 store 的动作
    actions: {
        updateSettings(settings: Partial<RoleShowCaseData>): void {
            // 使用 Object.assign 方法将传入的设置对象合并到当前 store 的状态中
            Object.assign(this.$state, settings)
        },

    },

    // 配置持久化选项
    persist: {
        // 存储键名
        key: 'ai-showcase',
        // 存储方式，这里使用的是 localStorage
        storage: localStorage,
    },
})

