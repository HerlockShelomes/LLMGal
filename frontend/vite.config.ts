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
      ignored: [
        '**/.git/**',
        '**/node_modules/**',
        '**/dist/**',
        '**/src/assets/voice/**',
        '**/src/assets/pictures/**',
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
