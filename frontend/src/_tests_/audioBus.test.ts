import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  claimPlayback,
  releasePlayback,
  stopAllPlayback,
  isPlaybackOwner,
} from '../utils/audioBus.ts';

/**
 * 这几条是「对话语音」与「设置面板试听音」互斥的契约。
 * 之前页面里两个 <audio> 各播各的，再加上 :key 重建元素，
 * 才会出现两段语音叠在一起。改动 audioBus 时这里必须保持全绿。
 */
describe('audioBus：全局单一发声通道', () => {
  let owners: Array<{ pause: ReturnType<typeof vi.fn> }>;

  const makeOwner = () => {
    const owner = { pause: vi.fn() };
    owners.push(owner);
    return owner;
  };

  beforeEach(() => {
    owners = [];
    stopAllPlayback();
  });

  it('新的发声者会先把上一个停掉', () => {
    const first = makeOwner();
    const second = makeOwner();

    claimPlayback(first);
    expect(first.pause).not.toHaveBeenCalled();

    claimPlayback(second);
    expect(first.pause).toHaveBeenCalledTimes(1);
    expect(second.pause).not.toHaveBeenCalled();
  });

  it('同一个发声者重复抢占不会把自己停掉', () => {
    const owner = makeOwner();

    claimPlayback(owner);
    claimPlayback(owner);

    expect(owner.pause).not.toHaveBeenCalled();
  });

  it('stopAllPlayback 停掉当前发声者，再次调用不会重复停', () => {
    const owner = makeOwner();

    claimPlayback(owner);
    stopAllPlayback();
    expect(owner.pause).toHaveBeenCalledTimes(1);

    stopAllPlayback();
    expect(owner.pause).toHaveBeenCalledTimes(1);
  });

  it('releasePlayback 让出通道后，stopAllPlayback 不会再停它', () => {
    const owner = makeOwner();

    claimPlayback(owner);
    releasePlayback(owner);
    stopAllPlayback();

    expect(owner.pause).not.toHaveBeenCalled();
  });

  it('发声者 pause 抛异常时不能影响抢占流程', () => {
    const broken = { pause: vi.fn(() => { throw new Error('元素已卸载'); }) };
    const next = makeOwner();

    claimPlayback(broken);
    expect(() => claimPlayback(next)).not.toThrow();
    expect(broken.pause).toHaveBeenCalledTimes(1);
  });

  // ChatView 的「被中断就自愈重播」看门狗靠 isPlaybackOwner 区分
  // 「被外部按停」（要重播）和「让位给别的发声者」（不能抢回来）。
  // 判错会让试听音和对话语音互相抢麦、循环打架。
  it('isPlaybackOwner 只在确实是自己占着通道时为真', () => {
    const first = makeOwner();
    const second = makeOwner();

    claimPlayback(first);
    expect(isPlaybackOwner(first)).toBe(true);
    expect(isPlaybackOwner(second)).toBe(false);

    // 被别人抢走后，原发声者必须让位
    claimPlayback(second);
    expect(isPlaybackOwner(first)).toBe(false);
    expect(isPlaybackOwner(second)).toBe(true);

    // 主动让出后谁也不占
    releasePlayback(second);
    expect(isPlaybackOwner(second)).toBe(false);
    expect(isPlaybackOwner(first)).toBe(false);
  });
});
