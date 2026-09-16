<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import { Fold, Expand, Plus, Delete, Edit, ArrowDown } from '@element-plus/icons-vue'
import { useChatStore } from '../stores/chat'
import { useRoleGroups, useRoleSession } from '../composables/useRoleSession.ts'
import RoleAvatar from './RoleAvatar.vue'
import { ElInput, ElMessageBox } from 'element-plus'

const isCollapsed = ref(false)
const chatStore = useChatStore()
const { enterConversation, createForRole, roleOptions } = useRoleSession()
const { groups } = useRoleGroups()

const activeId = computed(() => chatStore.activeConversationId)

const editingId = ref<string | null>(null)
const editTitle = ref('')
// 模板里的 ref="editInputRef" 在 v-for 中会被收集成数组，用联合类型兼容两种情况
const editInputRef = ref<InstanceType<typeof ElInput> | InstanceType<typeof ElInput>[] | null>(null)
// Esc 取消时会先置空 editingId 让输入框卸载，卸载又可能触发 blur 再保存一次，
// 用这个标记把由取消引起的 blur 挡掉
const isCancelling = ref(false)

// 分组折叠状态：只记录「被折叠」的角色，默认展开
const collapsedGroups = reactive(new Set<string>())

const toggleGroup = (roleValue: string) => {
  if (collapsedGroups.has(roleValue)) collapsedGroups.delete(roleValue)
  else collapsedGroups.add(roleValue)
}

const isGroupOpen = (roleValue: string) => !collapsedGroups.has(roleValue)

// ---------------------------------------------------------------------------
// 新建会话：先在按钮旁弹出角色下拉框，选中哪个角色就建哪个角色的会话
// ---------------------------------------------------------------------------
const createMenuVisible = ref(false)
// 正在为哪个角色创建会话：其头像位置显示滚动加载条
const creatingRole = ref<string | null>(null)

// 让加载条停留一小会儿。创建本身是同步的（只是往 store 里推一条记录），
// 不加这点延迟的话加载条只闪一帧，用户根本看不到。
const CREATE_FEEDBACK_MS = 400

const createForSelectedRole = async (roleValue: string) => {
  if (creatingRole.value) return
  creatingRole.value = roleValue
  try {
    await new Promise(resolve => window.setTimeout(resolve, CREATE_FEEDBACK_MS))
    createForRole(roleValue)
  } finally {
    creatingRole.value = null
    createMenuVisible.value = false
  }
}

const toggleSidebar = () => {
  isCollapsed.value = !isCollapsed.value
}

const switchConversation = (id: string) => {
  void enterConversation(id)
}

const deleteConversation = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个会话吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    const before = chatStore.activeConversationId
    chatStore.deleteConversation(id)
    // 删除的是当前会话时，store 会自动切到另一个会话；
    // 这里必须补一次「进入会话」，否则角色还停在被删会话的角色上。
    const after = chatStore.activeConversationId
    if (after && after !== before) {
      void enterConversation(after)
    }
  } catch {
    // 用户取消删除操作
  }
}

const startRename = async (conv: { id: string, title: string }, event: Event) => {
  event.stopPropagation()
  isCancelling.value = false
  editingId.value = conv.id
  editTitle.value = conv.title
  // 等输入框渲染出来再聚焦
  await nextTick()
  focusEditInput()
}

const focusEditInput = () => {
  const target = Array.isArray(editInputRef.value) ? editInputRef.value[0] : editInputRef.value
  target?.focus?.()
}

const saveRename = (conv: { id: string }) => {
  // 由 Esc 取消引发的 blur 不应再保存一次
  if (isCancelling.value) {
    isCancelling.value = false
    return
  }
  if (editTitle.value.trim()) {
    const conversation = chatStore.conversations.find(c => c.id === conv.id)
    if (conversation) {
      conversation.title = editTitle.value.trim()
    }
  }
  editingId.value = null
}

const cancelRename = () => {
  isCancelling.value = true
  editingId.value = null
}

const handleRenameKeydown = (conv: { id: string }, event: Event) => {
  const keyboardEvent = event as KeyboardEvent
  if (keyboardEvent.key === 'Enter') {
    keyboardEvent.preventDefault()
    saveRename(conv)
  } else if (keyboardEvent.key === 'Escape') {
    cancelRename()
  }
}
</script>

<template>
  <div class="sidebar" :class="{ 'collapsed': isCollapsed }">
    <div class="sidebar-header">
      <!-- 新建会话：先在按钮旁弹出角色选择，选中后才真正创建 -->
      <el-popover
        v-model:visible="createMenuVisible"
        placement="bottom-start"
        :width="220"
        trigger="click"
        popper-class="role-create-popper"
      >
        <template #reference>
          <el-button v-if="!isCollapsed" type="primary" class="new-chat-btn">
            <el-icon><Plus /></el-icon>新建会话
          </el-button>
          <el-button v-else circle type="primary" class="new-chat-btn">
            <el-icon><Plus /></el-icon>
          </el-button>
        </template>

        <div class="role-picker">
          <div class="role-picker-title">选择角色以创建会话</div>
          <div
            v-for="role in roleOptions"
            :key="role.value"
            class="role-picker-item"
            :class="{ 'is-creating': creatingRole === role.value }"
            @click="createForSelectedRole(role.value)"
          >
            <role-avatar
              :role-value="role.value"
              :label="role.label"
              :size="26"
              :loading="creatingRole === role.value"
            />
            <span class="role-picker-name">{{ role.label }}</span>
          </div>
        </div>
      </el-popover>
    </div>

    <div class="conversations-list">
      <!-- 按角色分组：每个角色一个可折叠的分组 -->
      <div v-for="group in groups" :key="group.roleValue" class="role-group">
        <div class="role-group-header" @click="toggleGroup(group.roleValue)">
          <role-avatar
            :role-value="group.roleValue"
            :label="group.roleLabel"
            :size="22"
          />
          <span v-if="!isCollapsed" class="role-group-name">
            {{ group.roleLabel }}
            <span v-if="group.missing" class="role-group-missing">（已删除）</span>
          </span>
          <span v-if="!isCollapsed" class="role-group-count">{{ group.conversations.length }}</span>
          <el-icon v-if="!isCollapsed" class="role-group-arrow" :class="{ 'is-closed': !isGroupOpen(group.roleValue) }">
            <ArrowDown />
          </el-icon>
        </div>

        <div v-show="isGroupOpen(group.roleValue)" class="role-group-body">
          <div v-for="conv in group.conversations"
               :key="conv.id"
               class="conversation-item"
               :class="{ 'active': conv.id === activeId }"
               @click="switchConversation(conv.id)">
            <!-- 角色小圆框图固定在标题最左侧 -->
            <role-avatar
              class="conversation-avatar"
              :role-value="conv.roleName"
              :label="conv.roleLabel"
              :size="20"
            />
            <div v-if="editingId === conv.id" class="conversation-edit" @click.stop>
              <el-input
                v-model="editTitle"
                size="small"
                @keydown="(e: Event) => handleRenameKeydown(conv, e)"
                @blur="saveRename(conv)"
                ref="editInputRef"
              />
            </div>
            <div v-else class="conversation-title" :title="conv.title">
              {{ isCollapsed ? '' : conv.title }}
            </div>
            <div v-if="!isCollapsed" class="conversation-actions">
              <el-button
                class="edit-btn"
                type="primary"
                link
                @click.stop="startRename(conv, $event)">
                <el-icon><Edit /></el-icon>
              </el-button>
              <el-button
                class="delete-btn"
                type="danger"
                link
                @click.stop="deleteConversation(conv.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!groups.length" class="empty-tip">
        {{ isCollapsed ? '' : '暂无会话，点击上方新建' }}
      </div>
    </div>

    <div class="collapse-btn" @click="toggleSidebar">
      <el-icon>
        <Fold v-if="!isCollapsed" />
        <Expand v-else />
      </el-icon>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.sidebar {
  width: 260px;
  height: 100%;
  flex-shrink: 0; /* 防止侧边栏被压缩 */
  background-color: var(--bg-color);
  border-right: 1px solid var(--border-color);
  transition: all 0.3s ease;
  position: relative;
  display: flex;
  flex-direction: column;

  &.collapsed {
    width: 60px;
  }
}

.sidebar-header {
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);

  :deep(.el-button) {
    width: 100%;
  }
}

/* 角色选择下拉框：头像左置、名称居中 */
.role-picker {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.role-picker-title {
  font-size: 12px;
  opacity: 0.6;
  padding: 2px 6px 6px;
}

.role-picker-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;

  &:hover {
    background-color: var(--el-fill-color-light);
  }

  &.is-creating {
    cursor: progress;
    opacity: 0.85;
  }
}

.role-picker-name {
  flex: 1;
  text-align: center;
  font-size: 14px;
}

.conversations-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
}

.role-group {
  margin-bottom: 6px;
}

.role-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border-radius: var(--border-radius);
  cursor: pointer;
  user-select: none;
  transition: background-color 0.2s;

  &:hover {
    background-color: var(--bg-color-secondary);
  }
}

.role-group-name {
  flex: 1;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-group-missing {
  font-weight: 400;
  opacity: 0.6;
}

.role-group-count {
  font-size: 12px;
  opacity: 0.55;
}

.role-group-arrow {
  font-size: 12px;
  transition: transform 0.2s;

  &.is-closed {
    transform: rotate(-90deg);
  }
}

.role-group-body {
  padding-left: 6px;
}

.conversation-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0.5rem;
  margin-bottom: 0.5rem;
  border-radius: var(--border-radius);
  cursor: pointer;
  transition: background-color 0.2s;

  &:hover {
    background-color: var(--bg-color-secondary);
    .conversation-actions {
      opacity: 1;
    }
  }

  &.active {
    background-color: var(--el-color-primary-light-9);
  }
}

.conversation-avatar {
  flex-shrink: 0;
}

.conversation-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-edit {
  flex: 1;
  margin-right: 0.5rem;

  :deep(.el-input__inner) {
    height: 24px;
    line-height: 24px;
  }
}

.conversation-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.edit-btn, .delete-btn {
  padding: 2px;
  height: 20px;

  .el-icon {
    font-size: 14px;
  }
}

.empty-tip {
  padding: 1rem 0.5rem;
  font-size: 12px;
  text-align: center;
  opacity: 0.55;
}

/* 修改 el-button 的默认样式 */
.el-button {
  background-color: #2196F3; /* 背景颜色改为蓝色 */
  border-color: #2196F3; /* 边框颜色改为蓝色 */
  color: white; /* 文字颜色保持为白色 */
  border-radius: var(--border-radius); /* 使用自定义变量设置圆角大小 */

  &:hover {
    background-color: #1976D2; /* 鼠标悬停时的背景颜色改为深蓝色 */

  }

  &:active {
    background-color: white; /* 按下时的背景颜色反转为白色 */

    color: #2196F3; /* 按下时的文字颜色反转为蓝色 */
  }
}

/* 修改 el-button 的圆形样式 */
.el-button.is-circle {
  background-color: #2196F3; /* 背景颜色改为蓝色 */
  border-color: #2196F3; /* 边框颜色改为蓝色 */
  color: white; /* 文字颜色保持为白色 */
  border-radius: var(--border-radius); /* 使用自定义变量设置圆角大小 */
  width: 40px; /* 可选：设置圆形按钮的宽度 */
  height: 40px; /* 可选：设置圆形按钮的高度 */
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    background-color: #1976D2; /* 鼠标悬停时的背景颜色改为深蓝色 */

  }
}

.collapse-btn {
  position: absolute;
  right: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 1;

  &:hover {
    background-color: var(--bg-color-secondary);
  }
}
</style>

<style lang="scss">
/* popper 被 teleport 到 body，非 scoped 才能命中 */
.role-create-popper {
  padding: 8px;
}
</style>
