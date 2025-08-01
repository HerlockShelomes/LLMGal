<script setup lang="ts">
import {ref, computed, watch} from 'vue'
import { Delete, Position, Upload, Plus, Document, VideoPlay } from '@element-plus/icons-vue'
import { useChatStore } from '../stores/chat.ts'
import { ElInput, ElMessage, ElMessageBox } from 'element-plus'
import {
  useSettingsStore,
} from '../stores/settings.ts'

// 定义组件的属性
const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  },
  generating: {
    type: Boolean,
    default: false
  },

  ix: {
    type: String,
    default: 'neutral'
  }
})

const settings = useSettingsStore();

// 定义组件的事件
const emit = defineEmits(['send', 'clear', 'stop'])

// 使用聊天存储
const chatStore = useChatStore()
// 消息文本的响应式引用
const messageText = ref('')

// 输入框的占位符
const placeholder = `输入消息，按Enter发送
Shift + Enter 换行`

const getImageUrl = (name: string, index: string) => {
  // 使用vite静态资源处理
  return new URL(`/src/assets/pictures/${name}/${name}_${index}.jpg`, import.meta.url).href
}

//要求这一部分跟随消息变换。
const i = ref<string>("neutral")
watch(
    () => props.ix,
    (newVal) => {
      i.value = newVal

      console.log('索引已更新', newVal)
    },
    { immediate: true }
)

// 计算属性，用于获取聊天存储中的Token计数
const tokenCount = computed(() => chatStore.currentTokenCount)

const showUpload = ref(false)
const selectedFiles = ref<File[]>([])

// 切换上传区域显示
const toggleUpload = () => {
  showUpload.value = !showUpload.value
}

// 处理文件选择
const handleFileChange = (file: { raw: File }) => {
  selectedFiles.value.push(file.raw)
}

// 移除文件
const removeFile = (index: number) => {
  selectedFiles.value.splice(index, 1)
}

// 判断是否为图片文件
const isImage = (file: File) => {
  return file.type.startsWith('image/')
}

// 获取预览URL
const getPreviewUrl = (file: File) => {
  return URL.createObjectURL(file)
}

// 修改发送处理函数
const handleSend = async () => {
  if ((!messageText.value.trim() && selectedFiles.value.length === 0) || props.loading) return

  try {
    // 处理文件上传
    const fileContents = await Promise.all(
      selectedFiles.value.map(async (file) => {
        if (isImage(file)) {
          return await convertImageToBase64(file)
        } else {
          return await readFileContent(file)
        }
      })
    )

    // 组合消息内容
    let content = messageText.value
    if (fileContents.length > 0) {
      content = content + '\n' + fileContents.join('\n')
    }

    emit('send', content)
    messageText.value = ''
    selectedFiles.value = []
    showUpload.value = false
  } catch (error) {
    console.error('发送失败:', error)
    ElMessage.error('发送失败，请重试')
  }
}

// 将图片转换为base64
const convertImageToBase64 = (file: File) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      resolve(`![${file.name}](${e.target?.result})`)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

// 读取文件内容
const readFileContent = (file: File) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      resolve(`\`\`\`\n${e.target?.result}\n\`\`\``)
    }
    reader.onerror = reject
    reader.readAsText(file)
  })
}

// 处理换行的函数
const newline = () => {}

// 处理清空对话的函数
const handleClear = async () => {
  try {
    // 使用Element Plus的消息框组件，提示用户是否确定清空对话记录
    await ElMessageBox.confirm(
      '确定要清空当前会话的所有对话记录吗？',
      '警告',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    // 如果用户确认清空，则触发clear事件
    emit('clear')
  } catch {
    // 如果用户取消操作，则不做任何事情
  }
}

const inputRef = ref<InstanceType<typeof ElInput> | null>(null)

// 调整输入框高度的方法
const adjustHeight = () => {
  if (inputRef.value) {
    // 获取输入框的DOM元素,因为是 ref，需要通过$el获取DOM元素
    const textarea = inputRef.value.$el.querySelector('textarea')
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${textarea.scrollHeight}px`
    }
  }
}

// 添加暂停处理函数
const handleStop = () => {
  emit('stop')
}
</script>

<template>
  <!-- 聊天输入容器 -->
  <div class="chat-input-container">
    <!-- 输入框和按钮的组合 -->
    <div class="input-wrapper">
      <!-- 添加文件上传区域 -->
      <div class="upload-area" v-if="showUpload">
        <el-upload class="upload-component" :action="null" :auto-upload="false" :on-change="handleFileChange"
          :show-file-list="false" multiple>
          <!-- trigger	触发文件选择框的内容 -->
          <template #trigger>
            <el-button type="primary" :icon="Plus">添加文件</el-button>
          </template>
        </el-upload>

        <!-- 预览区域 -->
        <div class="preview-list" v-if="selectedFiles.length">
          <div v-for="(file, index) in selectedFiles" :key="index" class="preview-item">
            <!-- 图片预览 -->
            <img v-if="isImage(file)" :src="getPreviewUrl(file)" class="preview-image" />
            <!-- 文件名预览 -->
            <div v-else class="file-preview">
              <el-icon>
                <Document />
              </el-icon>
              <span>{{ file.name }}</span>
            </div>
            <!-- 删除按钮 -->
            <el-button class="delete-btn" type="danger" :icon="Delete" circle @click="removeFile(index)" />
          </div>
        </div>
      </div>

      <div class="image-preview">
        <!---此处的index调用需要进行调用逻辑的修改，记得及时完成--->
        <img :src= "getImageUrl(settings.RoleConfig.roleName, i)" alt = "Role">
        <span v-if= "!getImageUrl(settings.RoleConfig.roleName, i)" class="place">+</span>
        <!---如果是引用放在public内的文件，就不需要目录回退。暂时原理并没特别理解，但至少要知道这一件事。--->
      </div>

      <el-input v-model="messageText" type="textarea" :rows="6" :autosize="{ minRows: 6, maxRows: 6 }"
        :placeholder="placeholder" resize="none" @keydown.enter.exact.prevent="handleSend"
        @keydown.enter.shift.exact="newline" @input="adjustHeight" ref="inputRef" />

      <div class="button-group">
        <!-- 添加切换上传区域的按钮 -->
        <el-tooltip content="上传文件" placement="top">
          <el-button circle :icon="Upload" @click="toggleUpload" />
        </el-tooltip>

        <el-tooltip content="清空对话" placement="top">
          <el-button circle type="danger" :icon="Delete" @click="handleClear" />
        </el-tooltip>

        <el-button 
          :type="generating ? 'danger' : 'primary'" 
          :loading="loading && !generating" 
          :class="{ 'pulsing-button': generating }"
          @click="generating ? handleStop() : handleSend()">
          <template #icon>
            <el-icon>
              <component :is="generating ? VideoPlay : Position" />
            </el-icon>
          </template>
          {{ generating ? 'Stop' : 'Send' }}
        </el-button>
      </div>
    </div>
    <!-- Token计数器 -->
    <div class="token-counter">
      已使用 Token: {{ tokenCount.total }} (提示: {{ tokenCount.prompt }}, 回复: {{ tokenCount.completion }})
    </div>
  </div>
</template>

<style lang="scss" scoped>
// 聊天输入容器的样式
.chat-input-container {
  padding: 0.3rem;
  background-color: var(--bg-color);
  border-top: 1px solid var(--border-color);
}
.el-button--primary {
  border-radius: var(--border-radius); /* 调整为你想要的圆角大小 */
}


// 输入框和按钮组合的样式
.input-wrapper {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.5rem;

  .image-preview {
    flex: 0 0 130px; // 固定正方形尺寸
    width: 130px;
    height: 130px;
    border: 2px dashed #ccc;
    border-radius: 8px;
    background: #f8f9fa;
    cursor: pointer;
    position: relative;
    transition: all 0.3s;

    &:hover {
      border-color: #409eff;
      background: #ecf5ff;
    }

    img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: 6px;
    }

    .place {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: #999;
      font-size: 24px;
    }

    .el-input {
      flex: 1;

      :deep(.el-textarea__inner) {
        transition: all 0.3s;
        line-height: 1.5;
        padding: 8px 12px;
        overflow-y: auto;

      }
    }
  }

  // 按钮组的样式
  .button-group {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    border-radius: var(--border-radius);
  }

  // Token计数器的样式
  .token-counter {
    font-size: 0.6rem;
    color: var(--text-color-secondary);
    text-align: center;
  }

  .upload-area {
    margin-bottom: 1rem;
    padding: 1rem;
    border: 2px dashed var(--border-color);
    border-radius: var(--border-radius);

    .preview-list {
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      margin-top: 1rem;

      .preview-item {
        position: relative;
        width: 100px;
        height: 100px;

        .preview-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
          border-radius: var(--border-radius);
        }

        .file-preview {
          width: 100%;
          height: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          background-color: var(--bg-color-secondary);
          border-radius: var(--border-radius);

          .el-icon {
            font-size: 2rem;
            margin-bottom: 0.5rem;
          }

          span {
            font-size: 0.8rem;
            text-align: center;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            width: 90%;
          }
        }

        .delete-btn {
          position: absolute;
          top: -0.5rem;
          right: -0.5rem;
          padding: 0.25rem;
          transform: scale(0.8);
          border-radius: var(--border-radius);
        }
      }
    }
  }

  .pulsing-button {
    animation: pulse 1.5s infinite;
    border-radius: var(--border-radius);

  }

  @keyframes pulse {
    0% {
      opacity: 1;
    }
    50% {
      opacity: 0.7;
    }
    100% {
      opacity: 1;
    }
  }
}
</style>