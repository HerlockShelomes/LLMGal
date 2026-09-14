/**
 * 全局单一发声通道。
 *
 * 背景：页面里有两个 <audio> 元素（ChatView 的对话语音、SettingsPanel 的试听音），
 * 且 ChatView 原先还用 :key 强制重建元素。三者各播各的，就会出现"两段语音重叠"。
 * 浏览器对「已移除的 media element」的 pause 是异步的，光靠 Vue 卸载元素
 * 并不能保证它立刻静音。
 *
 * 约定：任何地方要发声，先 claimPlayback() 抢占通道，
 * 通道会把上一个发声者 pause 掉。这样无论多少个 audio 元素，同一时刻只有一个在响。
 */

export interface PlaybackOwner {
    pause: () => void;
}

let current: PlaybackOwner | null = null;

/** 抢占发声通道：先把上一个发声者停掉。 */
export function claimPlayback(owner: PlaybackOwner): void {
    if (current && current !== owner) {
        try {
            current.pause();
        } catch {
            // 元素可能已被卸载，pause 抛错无需处理
        }
    }
    current = owner;
}

/** 主动让出通道（只有仍是自己占着时才清空，避免误清别人的）。 */
export function releasePlayback(owner: PlaybackOwner): void {
    if (current === owner) {
        current = null;
    }
}

/**
 * 当前发声者是不是就是自己。
 *
 * 用途：ChatView 有一套「被中断就自愈重播」的看门狗。当**另一个**发声者
 * （例如设置面板的试听音）抢占通道时，浏览器会 pause 掉对话语音——这是正常的
 * 让位，绝不能被看门狗当成故障重播，否则试听音和对话语音会互相抢麦。
 * 看门狗靠这个函数区分「被外部按停」和「正常让位」。
 */
export function isPlaybackOwner(owner: PlaybackOwner): boolean {
    return current === owner;
}

/** 停掉当前所有发声（点「停止生成」、切换会话时用）。 */
export function stopAllPlayback(): void {
    if (current) {
        try {
            current.pause();
        } catch {
            // 忽略
        }
        current = null;
    }
}
