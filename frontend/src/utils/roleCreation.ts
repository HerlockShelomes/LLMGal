// 角色创建进度轮询。
//
// 后端定稿（7 张情绪图 + 语音）要跑一两分钟，前端不能干等，只能轮询状态。
// 这个轮询器必须是**全局单例**且能自愈：
//   - 放在 SettingsPanel 里的话，用户中途刷新页面，creatingRoles 还留在
//     localStorage，但轮询器已经没了 —— 角色会永远卡在「创建中」，再也不能用。
//   - 所以抽到这里，ChatView 挂载时对「还在创建中」的角色重新挂上轮询。
import { useSettingsStore, API_BASE } from '../stores/settings.ts'

const timers = new Map<string, number>()

// 单次轮询间隔与总超时。7 张图 + 语音通常 1~3 分钟，给足 10 分钟兜底。
const POLL_INTERVAL = 2000
const MAX_WAIT = 10 * 60 * 1000

const clearTimer = (roleName: string) => {
  const timer = timers.get(roleName)
  if (timer) {
    window.clearInterval(timer)
    timers.delete(roleName)
  }
}

export function stopWatchingRole(roleName: string) {
  clearTimer(roleName)
}

export function stopWatchingAll() {
  timers.forEach(timer => window.clearInterval(timer))
  timers.clear()
}

/**
 * 盯住一个角色的创建进度，完成后把它从 creatingRoles 里摘掉。
 *
 * @param onDone 完成/失败回调（ok=false 时为失败或超时）
 */
export function watchRoleCreation(
  roleName: string,
  onDone?: (ok: boolean, error?: string) => void,
) {
  if (timers.has(roleName)) return

  const store = useSettingsStore()
  const startedAt = Date.now()

  const finish = (ok: boolean, error?: string) => {
    clearTimer(roleName)
    store.removeCreatingRole(roleName)
    onDone?.(ok, error)
  }

  const timer = window.setInterval(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/roles/status?role=${encodeURIComponent(roleName)}`)
      if (resp.ok) {
        const data = await resp.json()
        if (data.status === 'ready') {
          finish(true)
          return
        }
        if (data.status === 'failed') {
          finish(false, data.error || '未知错误')
          return
        }
      }
    } catch {
      // 后端短暂不可达：下一轮再试，不打扰用户
    }
    if (Date.now() - startedAt > MAX_WAIT) {
      finish(false, '创建超时')
    }
  }, POLL_INTERVAL)

  timers.set(roleName, timer)
}

/**
 * 页面（重新）加载后，把 localStorage 里残留的「创建中」角色重新挂上轮询。
 * 后端已经完成的会被立刻摘掉；后端重启过、查不到的会走超时兜底。
 */
export function reconcileCreatingRoles(onDone?: (role: string, ok: boolean, error?: string) => void) {
  const store = useSettingsStore()
  ;[...store.creatingRoles].forEach(roleName => {
    watchRoleCreation(roleName, (ok, error) => onDone?.(roleName, ok, error))
  })
}

/**
 * 拿后端磁盘上的权威名单，给 localStorage 里的自定义角色对账。
 *
 * localStorage 只是一份缓存。删除中途失败（例如页面被刷新打断）、在另一个
 * 标签页里删过、或者有人直接清过 assets 目录，缓存里都会留下磁盘上已经不存在
 * 的角色 —— 症状就是「角色明明删了，下拉框里还留着，再点删除又像是没反应」。
 * 这里把这类幽灵角色从缓存里摘掉，让界面和后端重新一致。
 *
 * 安全约束（宁可有脏数据，也不能误删用户自己的角色）：
 *   - 请求失败、响应非 2xx、或字段不是数组 → 一律不动；
 *   - 「创建中」的角色跳过：此刻文件还没落齐，按磁盘判断必然误判为已删除。
 *
 * @returns 被清理掉的幽灵角色名（调用方可据此提示用户）
 */
export async function reconcileCustomRoles(): Promise<string[]> {
  const store = useSettingsStore()

  let backendRoles: string[]
  try {
    const resp = await fetch(`${API_BASE}/api/roles/list`)
    if (!resp.ok) return []
    const data = await resp.json()
    if (!Array.isArray(data?.roles)) return []
    backendRoles = data.roles.map((name: unknown) => String(name))
  } catch {
    // 后端不可达：保持现状，下次挂载再对账
    return []
  }

  const alive = new Set(backendRoles)
  const ghosts = store.customRoles
    .map(role => role.value)
    .filter(name => !alive.has(name) && !store.creatingRoles.includes(name))

  ghosts.forEach(name => store.purgeRole(name))
  return ghosts
}
