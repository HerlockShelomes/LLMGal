import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './assets/styles/main.scss'
import App from './App.vue'

// 使用深色代码主题
import 'highlight.js/styles/github-dark.css'

// 会话结构升级为「会话绑定角色」，旧记录没有 roleName/roleLabel 无法归类，
// 一并清掉（旧持久化键）。新键是 ai-chat-history-v2，见 stores/chat.ts。
try {
  localStorage.removeItem('ai-chat-history')
} catch {
  // 隐私模式下 localStorage 可能不可写，忽略即可
}

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
app.use(ElementPlus)
app.mount('#app')
