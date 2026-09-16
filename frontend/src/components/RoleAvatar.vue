<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getImageUrl } from '../stores/settings.ts'

// 角色圆形头像：列表头部、会话条目、新建会话下拉框共用同一个实现，
// 避免三处各写一份图片兜底逻辑。
const props = withDefaults(defineProps<{
  roleValue: string
  label?: string
  size?: number
  // 正在创建会话：头像位置改显示滚动加载条
  loading?: boolean
}>(), {
  label: '',
  size: 24,
  loading: false,
})

const failed = ref(false)
// 换角色时要重置加载失败标记，否则会一直停在占位符上
watch(() => props.roleValue, () => { failed.value = false })

const url = computed(() => getImageUrl(props.roleValue, 'neutral'))
const showImage = computed(() => !!url.value && !failed.value)
const initial = computed(() => (props.label || props.roleValue || '?').trim().charAt(0) || '?')
</script>

<template>
  <span
    class="role-avatar"
    :class="{ 'is-loading': loading }"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${Math.max(10, size * 0.45)}px` }"
  >
    <img
      v-if="showImage"
      :src="url"
      :alt="label || roleValue"
      @error="failed = true"
    >
    <span v-else class="role-avatar-fallback">{{ initial }}</span>
    <!-- 滚动加载条：正在为这个角色创建会话 -->
    <span v-if="loading" class="role-avatar-spinner" :aria-label="'正在创建会话'" />
  </span>
</template>

<style lang="scss" scoped>
.role-avatar {
  position: relative;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: hidden;
  background-color: var(--bg-color-secondary);
  border: 1px solid var(--border-color);
  box-sizing: border-box;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.role-avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: var(--text-color-primary);
  opacity: 0.75;
}

.role-avatar-spinner {
  position: absolute;
  inset: -1px;
  border-radius: 50%;
  // 一段亮色弧线 + 透明底，转起来就是「滚动加载条」
  border: 2px solid transparent;
  border-top-color: #67c23a;
  border-right-color: #67c23a;
  animation: role-avatar-spin 0.7s linear infinite;
  background-color: rgba(0, 0, 0, 0.35);
}

@keyframes role-avatar-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
