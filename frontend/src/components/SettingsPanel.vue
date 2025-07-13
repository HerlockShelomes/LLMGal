<script setup lang="ts">
import {reactive, computed, ref, watchEffect, watch} from 'vue'
import {
  useSettingsStore,
  useModelOptions,
  type ModelOption,
  useRoleOptions,
  getImageUrl,
} from '../stores/settings.ts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Plus, InfoFilled } from '@element-plus/icons-vue'
import { ElTooltip } from 'element-plus'

// 定义组件的props
const props = defineProps({
  modelValue: Boolean
})

// 定义组件的emits
const emit = defineEmits(['update:modelValue'])

// 使用设置存储
const settingsStore = useSettingsStore()
const modelOptions = useModelOptions()
const roleOptions = useRoleOptions()

// 可见性计算属性，同步抽屉的可见性状态
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

// 设置对象，使用reactive进行响应式处理
const settings = reactive({
  isDarkMode: settingsStore.isDarkMode,
  modelText: settingsStore.modelText,
  modelVoice: settingsStore.modelVoice,
  modelImage: settingsStore.modelImage,
  temperature: settingsStore.temperature,
  maxTokens: settingsStore.maxTokens,
  apiKey: settingsStore.apiKey,
  streamResponse: settingsStore.streamResponse,
  topP: settingsStore.topP,
  topK: settingsStore.topK,
  frequencyPenalty: settingsStore.frequencyPenalty,
  t2iConfig: {
    imageSize: settingsStore.t2iConfig.imageSize,
    inferenceSteps: settingsStore.t2iConfig.inferenceSteps
  },
  RoleConfig: {
    roleName: settingsStore.RoleConfig.roleName,
    roleDescription: settingsStore.RoleConfig.roleDescription,
    roleImage: settingsStore.RoleConfig.roleImage,
  }
})




// 现阶段只允许文本模型发生更改。

// 新增：控制添加/编辑模型对话框的显示
const modelDialogVisible = ref(false)
const isEditing = ref(false)

const currentTextModel = ref<ModelOption>({
  label: '',
  value: '',
  type: 'plain'
})


// const currentVoiceModel = ref<ModelOption>({
//   label: '',
//   value: '',
//   type: 'voice'
// })
// const currentImageModel = ref<ModelOption>({
//   label: '',
//   value: '',
//   type: 'text2img'
// })

const originalModelValue = ref('')

// 检查模型value是否重复
const checkModelValueExists = (value: string, excludeValue?: string) => {
  // 检查是否与默认模型重复
  const defaultModelExists = modelOptions.value
    .filter(model => !settingsStore.customModels.includes(model))
    .some(model => model.value === value)
  
  if (defaultModelExists) {
    return '模型标识与默认模型重复'
  }


  // 检查是否与其他自定义模型重复(排除当前编辑的模型)
  const customModelExists = settingsStore.customModels
    .some(model => model.value === value && model.value !== excludeValue)
  
  if (customModelExists) {
    return '模型标识已存在'
  }

  return ''
}

const checkRoleOverlap = (value: string, excludeValue?: string) => {
  const defaultRoleOverlap = roleOptions.value
      .filter(role => !settingsStore.customRoles.includes(role))
      .some(role => role.value === value)

  if (defaultRoleOverlap) {
    return '角色名称重复'
  }

  //检查排除当前角色后是否与其他自定义角色重复：
  const customRoleOverlap = settingsStore.customRoles
      .some(role => role.value === value && role.value !== excludeValue)

  if (customRoleOverlap) {
    return '角色名称出现重复'
  }

  return ''
}

// 处理深色模式切换
const handleDarkModeChange = () => {
  settingsStore.toggleDarkMode()
}

// 保存设置
const handleSave = () => {
  settingsStore.updateSettings(settings)
  ElMessage.success('设置已保存')
  visible.value = false
}

// 打开添加模型对话框
const showAddModelDialog = () => {
  isEditing.value = false
  currentTextModel.value = {
    label: '',
    value: '',
    type: 'plain'
  }
  modelDialogVisible.value = true
}

// 打开编辑模型对话框
const showEditModelDialog = (model: ModelOption) => {
  isEditing.value = true
  currentTextModel.value = { ...model }
  originalModelValue.value = model.value
  modelDialogVisible.value = true
}

// 保存模型
const handleSaveModel = () => {
  if (!currentTextModel.value.label || !currentTextModel.value.value) {
    ElMessage.warning('请填写完整的模型信息')
    return
  }

  // 检查value值是否重复
  const errorMsg = checkModelValueExists(
    currentTextModel.value.value,
    isEditing.value ? originalModelValue.value : undefined
  )
  
  if (errorMsg) {
    ElMessage.warning(errorMsg)
    return
  }

  if (isEditing.value) {
    settingsStore.editCustomModel(originalModelValue.value, currentTextModel.value)
    if (settings.modelText === originalModelValue.value) {
      settings.modelText = currentTextModel.value.value
    }
  } else {
    settingsStore.addCustomModel(currentTextModel.value)
  }

  modelDialogVisible.value = false
  ElMessage.success(isEditing.value ? '模型已更新' : '模型已添加')
}

// 删除模型
const handleDeleteModel = async (model: ModelOption) => {
  try {
    await ElMessageBox.confirm('确定要删除这个模型吗？', '警告', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    // 删除模型
    settingsStore.removeCustomModel(model.value)
    
    // 如果删除的是当前选中的模型,切换到默认模型
    if (settings.modelText === model.value) {
      // 获取第一个非自定义模型作为默认模型
      const defaultModel = modelOptions.value.find(m => !settingsStore.customModels.includes(m))
      if (defaultModel) {
        settings.modelText = defaultModel.value
      }
    }
    
    ElMessage.success('模型已删除')
  } catch {
    // 用户取消删除
  }
}

// 获取模型类型标签文字
const getModelTypeLabel = (type: string) => {
  const typeMap: Record<string, string> = {
    'plain': '普通',
    'visual': '图生图',
    'text2img': '文生图',
    'voice': '语音'
  }
  return typeMap[type] || type
}

// 获取标签类型
const getModelTagType = (type: string) => {
  const typeMap: Record<string, '' | 'success' | 'warning' | 'info'> = {
    'plain': '',
    'visual': 'success',
    'text2img': 'success',
    'voice': 'warning'
  }
  return typeMap[type] || 'info'
}

const getRoleTagType = (type: string) => {
  const typeMap: Record<string, '' | 'success' | 'warning' | 'info'> = {
    '虚拟角色': 'warning',
    '数字分身': 'success',
  }
  return typeMap[type] || 'info'
}


// 图片尺寸选项
const imageSizeOptions = [
  { label: '1024x1024', value: '1024x1024' },
  { label: '960x1280', value: '960x1280' },
  { label: '768x1024', value: '768x1024' },
  { label: '720x1440', value: '720x1440' },
  { label: '720x1280', value: '720x1280' }
]

// 添加当前选中模型的类型计算属性
const currentModelText = computed(() => {
    const model = modelOptions.value.find(m => m.value === settings.modelText)
    return model?.type || 'plain'
})

const currentModelImage = computed(() => {
  const model = modelOptions.value.find(m => m.value === settings.modelImage)
  return model?.type || 'text2img'
})

// const currentRole = computed(() => {
//   const role = roleOptions.value.find(r => r.value === settings.RoleConfig.roleName)
//   return role?.type || '虚拟角色'
// })

const plainModelType = computed(() => {
  return modelOptions.value.filter(m => m.type === 'plain')
})

const text2picModelType = computed(() => {
  return modelOptions.value.filter(m => (m.type === 'text2img')||(m.type === 'visual'))
})

const voiceModelType = computed(() => {
  return modelOptions.value.filter(m => m.type === 'voice')
})

// 是否显示LLM/VLM相关设置
const showLLMSettings = computed(() => {
    return ['plain'].includes(currentModelText.value)
})

// 是否显示文生图相关设置
const showT2ISettings = computed(() => {
    return (currentModelImage.value === 'text2img') || (currentModelImage.value === 'visual')
})

// const logDebugInfo = (path: string, success: boolean) => {
//   if (import.meta.env.MODE === 'development') {
//     console.groupCollapsed('[文件加载调试]')
//     console.log('请求文件名: ', 'test')
//     console.log('完整路径: ', path)
//     console.log('加载状态: ', success ? '成功' : '失败')
//     console.groupEnd()
//   }
// }
//
// const loadFileContent = async (fileName: string) => {
//   try {
//     loading.value = true
//     errorMsg.value = ''
//     currentFilePath.value = getDescriptionFile(fileName)
//     if (import.meta.env.DEV) {
//       console.log('[DEV] 正在请求文件路径: ', currentFilePath.value)
//     }
//
//     const response = await fetch(currentFilePath.value)
//
//     if (!response.ok) {
//       throw new Error(`HTTP错误: ${response.status}`)
//     }
//
//
//     fileContent.value = await response.text()
//     errorMsg.value = ''
//
//     logDebugInfo(currentFilePath.value, true)
//   } catch (err) {
//     errorMsg.value = `加载失败: ${err instanceof Error ? err.message : '未知错误'}`
//
//     if (import.meta.env.DEV) {
//       console.error('文件加载错误: ', err)
//     }
//
//     logDebugInfo(currentFilePath.value, false)
//   } finally {
//     loading.value = false
//   }
// }


const showAvatar = ref<boolean>(true)
const handleImageError = () => {
  showAvatar.value = false
  ElMessage.warning('角色图片缺失')
}

const content = ref<string>('')
const errorMessage = ref<string>('')

const getRoleDocPath = (role_name: string) => {

  const basePath = import.meta.env.DEV
  ? new URL(`/src/assets/roles`, import.meta.url).href
  : '/assets/roles'

  return `${basePath}/${role_name}.txt`
}

//如果部署到服务器上，这里这段代码应当如何修改？
// const serverSideFetch = async (path: string) => {
//   const fs = await import('node.fs/promises')
//   return fs.readFile(new URL(path).pathname, 'utf-8')
// }
//服务器处理逻辑之后再确定。


watchEffect(async () => {
  const currentRole = settings.RoleConfig.roleName
  try {
    const docContent = await fetch(getRoleDocPath(currentRole))
            .then(read => read.ok ? read.text():Promise.reject('文档不存在'))
    content.value = docContent
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = `加载 ${currentRole} 文档失败: ${error instanceof Error ? error.message:error}`
    content.value = ''
  }

})

const getAudioUrl = (roleName: string) => {
  return new URL(`/src/assets/voice/${roleName}/${roleName}_test.mp3`, import.meta.url).href
}

const audio = ref()
const audioKey = ref(0)

const currentAudioUrl = computed(() =>
  getAudioUrl(settings.RoleConfig.roleName)
)

watch(() => settings.RoleConfig.roleName, (newRole) => {
  audioKey.value++
})

const play = () => {
  if (audio.value) {
      audio.value.play()
  }
}


const clickAudio = () => {
  play()
};


// const formatTime = (seconds: number) => {
//   const mins = Math.floor(seconds/60)
//   const secs = Math.floor(seconds%60)
//   return `${mins}:${secs.toString().padStrat(2, '0')}`
// }
//
//
// const audioElement = ref<HTMLAudioElement | null>(null)
// const isPlaying = ref(false)
// const currentTime = ref(0)
// const duration = ref(0)
//
// const audioUrl = computed(() => getAudioUrl(settings.RoleConfig.roleName))
//
// const togglePlay = () => {
//   if (isPlaying.value) {
//     audioElement.value.pause()
//   } else {
//     audioElement.value.play()
//   }
//
//   isPlaying.value = !isPlaying.value
// }
//
// const handleTimeUpdate = (e) => {
//   currentTime.value = e.target.currentTime
// }
//
// const hanldeLoadedMetadata = (e) => {
//   duration.value = e.target.durtion
// }
//
// watch (isPlaying, (newVal) => {
//   if (!audioElement.value) return
//
//   if (newVal) {
//     audioElement.value.play()
//   } else {
//     audioElement.value.pause()
//   }
// })

</script>

<template>
  <!-- 设置抽屉组件，用于展示和编辑应用设置 -->
  <el-drawer style="background-color: var(--bg-color);" v-model="visible" title="设置" direction="rtl" size="380px">
    <div class="settings-container">
      <!-- 使用element-plus的表单组件来展示和编辑设置 -->
      <el-form :model="settings" label-width="120px">
        <!-- 深色模式切换 -->
        <el-form-item label="深色模式">
          <el-switch v-model="settings.isDarkMode" @change="handleDarkModeChange" />
        </el-form-item>

        <!-- 模型选择 -->
        <el-form-item label="文本模型">
          <div class="model-selection">
            <el-select
              v-model="settings.modelText"
              class="w-full"
              :popper-class="'model-select-dropdown'"
            >
              <el-option
                v-for="model in plainModelType"
                :key="model.value"
                :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag 
                      size="small" 
                      :type="getModelTagType(model.type)"
                      class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
          <div class="add-model-button">
            <el-button type="primary" link @click="showAddModelDialog">
              <el-icon><Plus /></el-icon>
              添加模型
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="语音模型">
          <div class="model-selection">
            <el-select
                v-model="settings.modelVoice"
                class="w-full"
                :popper-class="'model-select-dropdown'"
            >
              <el-option
                  v-for="model in voiceModelType"
                  :key="model.value"
                  :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                  :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag
                        size="small"
                        :type="getModelTagType(model.type)"
                        class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
        </el-form-item>

        <el-form-item label="图像模型">
          <div class="model-selection">
            <el-select
                v-model="settings.modelImage"
                class="w-full"
                :popper-class="'model-select-dropdown'"
            >
              <el-option
                  v-for="model in text2picModelType"
                  :key="model.value"
                  :label="`${getModelTypeLabel(model.type)} | ${model.label}`"
                  :value="model.value"
              >
                <div class="model-option">
                  <div class="model-info">
                    <el-tag
                        size="small"
                        :type="getModelTagType(model.type)"
                        class="model-type-tag"
                    >
                      {{ getModelTypeLabel(model.type) }}
                    </el-tag>
                    <span>{{ model.label }}</span>
                  </div>
                  <div v-if="settingsStore.customModels.includes(model)" class="model-actions">
                    <el-button link type="primary" @click.stop="showEditModelDialog(model)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                    <el-button link type="danger" @click.stop="handleDeleteModel(model)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>
              </el-option>
            </el-select>
          </div>
        </el-form-item>

        <el-form-item label="角色选择">
          <div class="select-box">
          <span class="label">
            <!---这一行span可能可以删掉--->
          <el-select
              v-model="settings.RoleConfig.roleName"
              placeholder="请选择角色"
              class="w-full"
              :popper-class="'model-select-dropdown'"
          >
            <el-option
                v-for="role in roleOptions"
                :key="role.value"
                :label="`${(role.type)} | ${role.label}`"
                :value="role.value"
            >

              <div class="role-option">
                <div class="role-info">
                  <el-tag
                      size="samll"
                      :type="getRoleTagType(role.type)"
                      class="role-type-tag"
                  >
                    {{ role.type }}
                  </el-tag>
                  <span>{{ role.label }}</span>
                </div>
                <div v-if="settingsStore.customRoles.includes(role)" class="role-actions">
                  <!---此处需要完善增删角色逻辑--->
                </div>
              </div>
            </el-option>
          </el-select>
          </span>
          </div>
        </el-form-item>


        <div class="function-box document-viewer">
          <div class="scroll-container">
            <div v-if="!content && errorMessage" class="loading">选择角色查看文档</div>

            <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

            <pre v-else class="content">{{ content }}</pre>
          </div>
        </div>


        <div class="function-box avatar-box">
          <img
              :src="getImageUrl(settings.RoleConfig.roleName,'neutral')"
              alt="角色形象"
              class="role-avatar"
              @error="handleImageError"
          >
          <div v-if="!getImageUrl(settings.RoleConfig.roleName,'neutral')" class="avatar-placeholder">
            显示失败
            <i class="el-icon-picture-outline"></i>
          </div>
        </div>

        <div>这个角色在向你打招呼</div>
        <audio ref="audio" :key="audioKey">
          <source :src="currentAudioUrl" type="audio/mpeg" />
        </audio>

        <el-button class="play-button"
        @click="clickAudio()"
        >▶</el-button>

        <!-- LLM/VLM设置 -->
        <template v-if="showLLMSettings">
          <el-divider>模型参数</el-divider>
          <!-- Temperature设置-->

          <!-- API Key输入 -->
          <el-form-item label="API Key">
            <el-input v-model="settings.apiKey" type="password" show-password placeholder="请输入API Key" />
          </el-form-item>

          <el-form-item label="Temperature">
            <el-slider v-model="settings.temperature" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
          <!-- 最大Token设置 -->
          <el-form-item label="最大Token">
            <el-input-number v-model="settings.maxTokens" :min="1" :max="4096" :step="1" />
          </el-form-item>
          <!-- 流式响应 -->
          <el-form-item>
            <template #label>
              流式响应
              <el-tooltip content="开启将后将实时显示AI回复" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-switch v-model="settings.streamResponse" />
          </el-form-item>
          <!-- Top P设置 -->
          <el-form-item label="Top P">
            <el-slider v-model="settings.topP" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
          <!-- Top K设置 -->
          <el-form-item label="Top K">
            <el-input-number v-model="settings.topK" :min="1" :max="100" :step="1" />
          </el-form-item>
          <!-- Frequency Penalty -->
          <el-form-item>
            <template #label>
              重复惩罚
              <el-tooltip content="控制模型重复使用相同词语的倾向，值越大越不倾向重复" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-slider 
              v-model="settings.frequencyPenalty" 
              :min="-2" 
              :max="2" 
              :step="0.1" 
              show-input
            />
          </el-form-item>
        </template>

        <!-- 文生图设置 -->
        <template v-if="showT2ISettings">
          <el-divider>文生图模型参数</el-divider>
          
          <el-form-item label="图片尺寸">
            <el-select
              v-model="settings.t2iConfig.imageSize"
              class="w-full"
            >
              <el-option
                v-for="option in imageSizeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item>
            <template #label>
              推理步数
              <el-tooltip content="控制生成图像的精细程度，值越大生成图像越精细" placement="top">
                <el-icon class="info-icon"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-slider
              v-model="settings.t2iConfig.inferenceSteps"
              :min="10"
              :max="50"
              :step="1"
              show-input
            />
          </el-form-item>
        </template>
      </el-form>



      <!-- 保存设置按钮 -->
      <div class="settings-footer">
        <el-button type="primary" @click="handleSave">保存设置</el-button>
      </div>
    </div>

    <!-- 添加/编辑模型对话框 -->
    <el-dialog
      :title="isEditing ? '编辑模型' : '添加模型'"
      v-model="modelDialogVisible"
      width="500px"
    >
      <el-form :model="currentModelText" label-width="100px">
        <el-form-item label="模型名称">
          <el-input v-model="currentTextModel.label" placeholder="请输入模型名称(DS-R1)" />
        </el-form-item>
        <el-form-item label="模型标识">
          <el-input v-model="currentTextModel.value" placeholder="请输入模型标识(deepseek-ai/DeepSeek-R1)" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-select v-model="currentTextModel.type">
            <el-option label="普通对话" value="plain" />
            <el-option label="视觉模型" value="visual" />
            <el-option label="文生图" value="text2img" />
            <el-option label="语音" value="voice"/>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveModel">确定</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<style lang="scss" scoped>
:deep(.model-select-dropdown) {
  .el-select-dropdown__item {
    padding: 0 12px;
  }
}

// 设置页面样式
.settings-container {
  padding: 1rem;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

// 保存按钮布局
.settings-footer {
  margin-top: auto;
  padding-top: 1rem;
  text-align: right;
}

// 全宽样式，用于表单项
.w-full {
  width: 100%;
}

// 表单项提示样式
.form-item-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.model-selection {
  width: 100%;
}

.select-box {
  cursor: pointer;
  width: 100%;
}

.add-model-button {
  margin-top: 8px;
}

.model-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.role-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.model-actions {
  display: flex;
  gap: 4px;
}

.info-icon {
  margin-left: 4px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  cursor: help;
}


.model-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.role-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-type-tag {
  font-size: 12px;
  padding: 0 4px;
  height: 20px;
  line-height: 18px;
}

.role-type-tag {
  font-size: 12px;
  padding: 0 4px;
  height: 20px;
  line-height: 18px;
}

.function-box {
  background: white;
  border-radius: 12px;
  padding: 15px;
  box-shadow: 0 2px 4px 0 rgba(0,0,0,0.1);
}

.document-viewer {
  flex: 1;
  max-width: 400px;
}

.scroll-container {
  height:300px;
  overflow-y: auto;
  background: #fafafa;
  border-radius: 6px;
  padding: 10px;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 1em;
  font-weight: bolder;
}

.avatar-box {
  width: 250px;
  height: 250px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

.role-avatar {
  width: 100%;
  height:100%;
  object-fit: cover;
  border-radius: 8px;
}

.avatar-placeholder {
  font-size: 40px;
  color: #ddd;
}

.audio-control {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}

.play-button {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: #646cff;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;
}

.play-button:hover {
  background: #90caf9;
}

.time-display {
  font-family: monospace;
  color: #1a1a1a;
}

</style>