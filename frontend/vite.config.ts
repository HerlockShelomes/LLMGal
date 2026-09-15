import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

const getDynamicPath = (...segments: string[]) =>
    path.resolve(process.cwd(), ...segments)

// https://vitejs.dev/config/
export default defineConfig({
  assetsInclude: ['**/*.jpg', '**/*.png', '**/*.txt'],
  plugins: [vue()],
  server: {
    watch: {
      // 后端每轮都会往这两个目录写新文件（语音 wav/mp3、情绪图片），
      // 而 stores/settings.ts 用 import.meta.glob(..., { eager: true })
      // **静态引用**了它们 —— Vite 因此判定模块失效并触发 HMR / 整页重载，
      // 后果是「新一轮语音刚响就被掐掉、控制台被清空」，排查时极具误导性。
      // 这些文件本来就是后端生成物，不需要热更新：
      // getAudioUrls() 在 dev 下已改为直连磁盘路径 + 时间戳破缓存，不依赖 glob 快照。
      //
      // roles/ 是同一类问题：角色设定也走 import.meta.glob(eager)，而「删除角色」
      // 会删掉 roles/<角色>.txt —— 文件一消失，Vite 判定这个 glob 模块失效、
      // 直接整页重载，把刚弹出的成功提示一起刷掉。删除/创建都是后端写盘行为，
      // 不该触发前端热更新（getDescriptionFiles() 在 dev 下同样有直连磁盘的兜底）。
      ignored: [
        '**/.git/**',
        '**/node_modules/**',
        '**/dist/**',
        '**/src/assets/voice/**',
        '**/src/assets/pictures/**',
        '**/src/assets/roles/**',
      ],
    },
  },
  resolve: {
    alias: {
      '@images': getDynamicPath('src/assets/pictures'),
      '@': getDynamicPath('src'),
      ...(process.env.NODE_ENV === 'production' ? {
        '@cdn': getDynamicPath('public/external-assets')
      } : {})
    },
  },

})
