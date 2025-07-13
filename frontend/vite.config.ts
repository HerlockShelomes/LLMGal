import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

const getDynamicPath = (...segments: string[]) =>
    path.resolve(process.cwd(), ...segments)

// https://vitejs.dev/config/
export default defineConfig({
  assetsInclude: ['**/*.jpg', '**/*.png', '**/*.txt'],
  plugins: [vue()],
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
