<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { roleNotice, resolveRoleNotice } from '../composables/useRoleSession.ts'

// 全站只挂一个实例（挂在 ChatView）：状态在 useRoleSession 里是模块级单例。
// Esc 等同于取消；「角色已删除」这类只有确认按钮的提示按确认处理。
const onKeydown = (e: KeyboardEvent) => {
  if (!roleNotice.visible || e.key !== 'Escape') return
  e.preventDefault()
  resolveRoleNotice(!roleNotice.showCancel)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <teleport to="body">
    <transition name="role-notice">
      <div v-if="roleNotice.visible" class="role-notice-mask" @click.self="resolveRoleNotice(false)">
        <div class="role-notice-box" role="alertdialog" aria-modal="true">
          <div class="role-notice-text">{{ roleNotice.message }}</div>
          <div class="role-notice-btns">
            <button type="button" class="notice-btn confirm" @click="resolveRoleNotice(true)">
              {{ roleNotice.confirmText }}
            </button>
            <button v-if="roleNotice.showCancel" type="button" class="notice-btn cancel" @click="resolveRoleNotice(false)">
              取消
            </button>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<style lang="scss" scoped>
.role-notice-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: rgba(0, 0, 0, 0.45);
}

.role-notice-box {
  min-width: 300px;
  max-width: 420px;
  padding: 20px 22px 16px;
  border-radius: 8px;
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.25);
}

.role-notice-text {
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-color-primary);
  margin-bottom: 20px;
}

.role-notice-btns {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.notice-btn {
  min-width: 76px;
  height: 32px;
  padding: 0 16px;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s, border-color 0.2s;
}

// 确认在左：白底，移上去变绿
.confirm {
  background-color: #ffffff;
  border: 1px solid #dcdfe6;
  color: #303133;

  &:hover {
    background-color: #67c23a;
    border-color: #67c23a;
    color: #ffffff;
  }
}

// 取消在右：红底，移上去变白
.cancel {
  background-color: #f56c6c;
  border: 1px solid #f56c6c;
  color: #ffffff;

  &:hover {
    background-color: #ffffff;
    border-color: #f56c6c;
    color: #f56c6c;
  }
}

.role-notice-enter-active,
.role-notice-leave-active {
  transition: opacity 0.2s;

  .role-notice-box {
    transition: transform 0.2s;
  }
}

.role-notice-enter-from,
.role-notice-leave-to {
  opacity: 0;

  .role-notice-box {
    transform: translateY(-8px);
  }
}
</style>
