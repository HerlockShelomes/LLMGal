import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * 音频播放链路的回归测试。
 *
 * 背景（三批坑，别再踩回去）：
 *   1) ChatView 里曾经同时存在 watch(currentAudioUrl)、:key 重建 <audio>、
 *      @canplay 自动 play() 三套机制，互相打架 → 两段语音重叠。
 *   2) 改成单一命令式 playAudio() 之后，超时兜底在 readyState=0 时就 play()，
 *      promise 被挂住很久，落定时已经是过期请求 → 出现过「完全没有声音」。
 *   3) 最隐蔽的一条：过期请求的 .then() 里写了 `if (token !== playToken) el.pause()`。
 *      **对的是同一个 <audio> 元素**，所以那一刀 pause() 停掉的是刚开始播的新语音。
 *      日志表现极具误导性：`play() 已被接受` + `paused=true currentTime=0 error=无`。
 *
 * 本文件锁死的是：
 *   - 收到响应后 src 一定被赋值、load() 一定被调用（不 load 就永远 readyState=0）；
 *   - readyState < 2 时绝不 play()，到 2 之后才 play()，且只 play 一次；
 *   - 连续两轮：第二轮先 pause，页面上只有一个 audio 元素；
 *   - **过期请求迟到落定时不得调用 pause()**（第 3 条坑的回归测试）。
 */

// jsdom 不实现媒体播放，打桩并记录调用
let fakeReadyState = 0;
let playImpl: () => Promise<void> = () => Promise.resolve();
let resolvePendingPlay: (() => void) | null = null;

const playSpy = vi.fn(() => playImpl());
const pauseSpy = vi.fn();
const loadSpy = vi.fn();

Object.defineProperty(HTMLMediaElement.prototype, 'play', {
  value: playSpy,
  writable: true,
  configurable: true,
});
Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
  value: pauseSpy,
  writable: true,
  configurable: true,
});
Object.defineProperty(HTMLMediaElement.prototype, 'load', {
  value: loadSpy,
  writable: true,
  configurable: true,
});
// readyState 必须可控：实现里是「轮询等到 >=2 才 play()」
Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
  get: () => fakeReadyState,
  configurable: true,
});

const { managerRef } = vi.hoisted(() => ({ managerRef: { current: null as any } }));

vi.mock('../utils/WebSocketManager.ts', () => {
  class FakeWebSocketManager {
    handlers: Record<string, Array<(data: unknown) => void>> = {};

    constructor(_url?: string) {
      managerRef.current = this;
    }

    on(event: string, handler: (data: unknown) => void) {
      (this.handlers[event] ||= []).push(handler);
    }

    off() {}
    send() {}
    disconnect() {}
    connect() {
      return Promise.resolve();
    }

    emit(event: string, data?: unknown) {
      (this.handlers[event] || []).forEach((h) => h(data));
    }
  }

  return { WebSocketManager: FakeWebSocketManager };
});

const buildResponse = (index: string) => ({
  type: 'assistant_response',
  message_id: 'msg-1',
  status: 'success',
  payload: {
    response: '(高兴)你好呀',
    emotion: 'happy',
    index,
    metrics: { time_cost: 1.2, tokens_used: 30 },
    imageUrl: '',
  },
});

async function mountChatView() {
  const ChatView = (await import('../views/ChatView.vue')).default;
  const wrapper = mount(ChatView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        SideBar: true,
        SearchBar: true,
        ChatMessage: true,
        ChatInput: true,
        SettingsPanel: true,
      },
    },
  } as never);
  mounted.push(wrapper);
  return wrapper;
}

// 必须逐个卸载：组件不卸载的话，它的「等数据轮询」和「自愈复查」定时器
// 会活到下一个用例里，把 play() 打到下一个用例的 spy 上（用例互相污染）。
const mounted: Array<{ unmount: () => void }> = [];

afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
});

// 实现里是 150ms 轮询等数据，这里给足几个轮询周期
const settle = () => new Promise((r) => setTimeout(r, 320));
// 首次 mount 要连带 transform 整个 ChatView 依赖树，给宽一点
const CASE_TIMEOUT = 20000;

describe('ChatView 语音播放链路', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    playSpy.mockClear();
    pauseSpy.mockClear();
    loadSpy.mockClear();
    managerRef.current = null;
    fakeReadyState = 0;
    resolvePendingPlay = null;
    playImpl = () => Promise.resolve();
    localStorage.clear();
  });

  it('收到响应后设置 src 并 load()，但要等到 readyState>=2 才 play()', async () => {
    const wrapper = await mountChatView();
    await flushPromises();

    const audioEl = wrapper.find('audio').element as HTMLAudioElement;
    expect(audioEl).toBeTruthy();

    managerRef.current.emit('message', buildResponse('2'));
    await flushPromises();
    await settle();

    // src 必须被真正赋值；为空说明 getAudioUrls 没解析到资源，用户就会听不到声音
    expect(audioEl.getAttribute('src')).toBeTruthy();
    expect(audioEl.getAttribute('src')).toContain('_2_Stream');
    // 不 load() 的话 readyState 永远停在 0，表现为「等不到数据也没声音」
    expect(loadSpy).toHaveBeenCalled();
    // 先停后播：新的播放开始前必须先把旧的静音（两段重叠的防线）
    expect(pauseSpy).toHaveBeenCalled();
    // readyState 还是 0：此时 play() 的 promise 会被挂住，绝不能播
    expect(playSpy).not.toHaveBeenCalled();

    fakeReadyState = 2;
    await settle();
    expect(playSpy).toHaveBeenCalledTimes(1);
  }, CASE_TIMEOUT);

  it('连续两轮：第二次先 pause，页面只有一个 audio 元素', async () => {
    const wrapper = await mountChatView();
    await flushPromises();
    const audioEl = wrapper.find('audio').element as HTMLAudioElement;

    fakeReadyState = 2;
    managerRef.current.emit('message', buildResponse('2'));
    await settle();
    const pauseAfterFirst = pauseSpy.mock.calls.length;
    expect(playSpy).toHaveBeenCalledTimes(1);

    managerRef.current.emit('message', buildResponse('3'));
    await settle();

    // 第二轮也必须先 pause
    expect(pauseSpy.mock.calls.length).toBeGreaterThan(pauseAfterFirst);
    expect(audioEl.getAttribute('src')).toContain('_3_Stream');
    // 页面上只应有一个 audio 元素在发声（第二个来自设置面板，此处已 stub）
    expect(wrapper.findAll('audio').length).toBe(1);
    expect(playSpy).toHaveBeenCalledTimes(2);
  });

  it('过期请求迟到落定时，绝不能再 pause()（否则会掐掉新一轮的语音）', async () => {
    const wrapper = await mountChatView();
    await flushPromises();
    const audioEl = wrapper.find('audio').element as HTMLAudioElement;

    // 第一轮的 play() 故意「挂住不落定」，模拟 readyState 迟到就绪
    playImpl = () =>
      new Promise<void>((resolve) => {
        resolvePendingPlay = resolve;
      });

    fakeReadyState = 2;
    managerRef.current.emit('message', buildResponse('2'));
    await settle();
    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(resolvePendingPlay).toBeTruthy();

    // 第二轮正常落定
    playImpl = () => Promise.resolve();
    managerRef.current.emit('message', buildResponse('3'));
    await settle();
    expect(audioEl.getAttribute('src')).toContain('_3_Stream');
    expect(playSpy).toHaveBeenCalledTimes(2);

    // 关键：现在让第一轮的 play() 迟到落定
    const pauseBeforeStaleResolve = pauseSpy.mock.calls.length;
    const resolveStale = resolvePendingPlay as unknown as () => void;
    resolveStale();
    await settle();

    // 同一个 <audio> 元素上的补刀 pause() 会掐掉第三轮的语音 —— 一行都不能加回来
    expect(pauseSpy.mock.calls.length).toBe(pauseBeforeStaleResolve);
    // 过期请求也不该再发起新的播放
    expect(playSpy).toHaveBeenCalledTimes(2);
  }, CASE_TIMEOUT);
});
