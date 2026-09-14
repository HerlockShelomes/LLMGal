/**
 * 运行时模式（Mock / 正式版）的前端出入口。
 *
 * 真相源在后端：backend/runtime_mode.json，经 /api/system/mode 读写。
 * 前端在 store 里只留一份「镜像」用于展示 —— 不要在本地猜模式，否则出现
 * 「手工改过后端开关文件」或「另一个标签页切过」时，界面显示会与实际不符。
 */
import { ElMessage } from 'element-plus'
import { API_BASE, APP_MODE_LABELS, useSettingsStore, type AppMode } from '../stores/settings.ts'

export interface AppModeState {
  mode: AppMode
  label: string
  mock: boolean
}

const normalizeMode = (value: unknown): AppMode => (value === 'mock' ? 'mock' : 'prod')

const toState = (data: unknown): AppModeState => {
  const record = (data ?? {}) as { mode?: unknown; label?: unknown }
  const mode = normalizeMode(record.mode)
  const label = typeof record.label === 'string' && record.label
    ? record.label
    : APP_MODE_LABELS[mode]
  return { mode, label, mock: mode === 'mock' }
}

/** 读取后端当前模式。后端不可达时返回 null —— 调用方保持现状，而不是瞎猜一个。 */
export const fetchAppMode = async (): Promise<AppModeState | null> => {
  try {
    const resp = await fetch(`${API_BASE}/api/system/mode`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return toState(await resp.json())
  } catch (error) {
    console.warn('[模式] 读取后端运行时模式失败：', error)
    return null
  }
}

/** 切换后端模式。失败时给出可读提示并返回 null（界面状态不变）。 */
export const switchAppMode = async (mode: AppMode): Promise<AppModeState | null> => {
  try {
    const resp = await fetch(`${API_BASE}/api/system/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(detail?.detail || `HTTP ${resp.status}`)
    }
    return toState(await resp.json())
  } catch (error) {
    console.error('[模式] 切换运行时模式失败：', error)
    ElMessage.error(`模式切换失败：${error instanceof Error ? error.message : error}`)
    return null
  }
}

/** 把后端模式同步进 store；返回同步结果供调用方决定是否提示。 */
export const syncAppModeFromBackend = async (): Promise<AppModeState | null> => {
  const state = await fetchAppMode()
  if (state) {
    useSettingsStore().setAppMode(state.mode)
  }
  return state
}
