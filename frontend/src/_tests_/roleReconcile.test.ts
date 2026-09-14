import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { defaultRole, useSettingsStore } from '../stores/settings';
import { reconcileCustomRoles } from '../utils/roleCreation';

/**
 * 自定义角色缓存的自我对账（reconcileCustomRoles）。
 *
 * 背景（真实缺陷）：localStorage 里的自定义角色只是一份缓存。删除流程被页面刷新
 * 打断时 purgeRole 从没执行过，缓存里就留下一个磁盘上早已被删掉的角色 ——
 * 界面上表现为「明明删了，下拉框里还在，再点删除又像是没反应」。
 * 这里用后端的权威名单把它摘掉。
 *
 * 反向约束同样重要：**对账失败时绝不能动用户的数据**。后端抖一下、返回体结构变了，
 * 都不允许把用户自己的角色清空 —— 宁可留着脏数据，也不能误删。
 */

const GHOST = '林彻';   // 磁盘上已不存在
const ALIVE = '林亦';   // 磁盘上还在

const stubFetch = (payload: unknown, ok = true) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok,
      status: ok ? 200 : 500,
      json: async () => payload,
    })),
  );
};

const stubFetchReject = () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('后端不可达'); }));
};

describe('reconcileCustomRoles', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('磁盘上已经没有的角色被摘掉，还在的保留', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });
    store.addNewRole({ label: ALIVE, value: ALIVE, type: '虚拟角色' });
    store.setCustomRoleDetail(GHOST, { personality: 'x', voiceId: 'Mia', imageDescription: 'y' });

    stubFetch({ roles: [ALIVE] });
    const ghosts = await reconcileCustomRoles();

    expect(ghosts).toEqual([GHOST]);
    expect(store.customRoles.map(r => r.value)).toEqual([ALIVE]);
    expect(store.customRoleDetails[GHOST]).toBeUndefined();
  });

  it('清掉的正是当前选中角色时，回退到内置默认角色', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });
    store.RoleConfig.roleName = GHOST;

    stubFetch({ roles: [] });
    await reconcileCustomRoles();

    expect(store.RoleConfig.roleName).toBe(defaultRole[0].value);
  });

  it('后端不可达时一个都不动（宁可留脏数据，也不能误删）', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });

    stubFetchReject();
    const ghosts = await reconcileCustomRoles();

    expect(ghosts).toEqual([]);
    expect(store.customRoles.map(r => r.value)).toEqual([GHOST]);
  });

  it('后端返回非 2xx 时一个都不动', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });

    stubFetch({ detail: '内部错误' }, false);
    const ghosts = await reconcileCustomRoles();

    expect(ghosts).toEqual([]);
    expect(store.customRoles.map(r => r.value)).toEqual([GHOST]);
  });

  it('返回体结构不对（roles 不是数组）时一个都不动', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });

    stubFetch({ roles: 'oops' });
    const ghosts = await reconcileCustomRoles();

    expect(ghosts).toEqual([]);
    expect(store.customRoles.map(r => r.value)).toEqual([GHOST]);
  });

  it('「创建中」的角色即使磁盘上查不到也不动（此刻文件还没落齐）', async () => {
    const store = useSettingsStore();
    store.addNewRole({ label: GHOST, value: GHOST, type: '虚拟角色' });
    store.addCreatingRole(GHOST);

    stubFetch({ roles: [] });
    const ghosts = await reconcileCustomRoles();

    expect(ghosts).toEqual([]);
    expect(store.customRoles.map(r => r.value)).toEqual([GHOST]);
  });
});

/**
 * 模板层的回归闸门：**全项目**的原生 <button> 必须显式声明 type。
 *
 * 真实事故：删除角色按钮写成裸 <button>，而它落在 <el-form> 里。
 * Element Plus 的 el-form 渲染出的就是原生 <form>
 * （node_modules/element-plus/es/components/form/src/form2.mjs 里
 * `createElementBlock("form", ...)`），而原生 button 缺省 type 为 submit ——
 * 于是点击的瞬间表单提交、整页刷新，用户根本来不及看清确认弹窗。
 *
 * 这类缺陷编译、类型检查、单测都发现不了（不报错、不抛异常，只是页面重载），
 * 只能在模板上钉一条断言；而且必须扫全项目，否则下一个组件会重犯。
 */
const collectVueFiles = (dir: string, out: string[] = []): string[] => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) collectVueFiles(full, out);
    else if (entry.name.endsWith('.vue')) out.push(full);
  }
  return out;
};

describe('模板守卫：原生 button 必须带 type', () => {
  it('全项目没有缺 type 的裸 <button>（在 el-form 内会触发提交导致整页刷新）', () => {
    const here = path.dirname(fileURLToPath(import.meta.url));
    const srcRoot = path.resolve(here, '..');
    const files = collectVueFiles(srcRoot);

    expect(files.length).toBeGreaterThan(0);

    const offenders: string[] = [];
    for (const file of files) {
      const tags = fs.readFileSync(file, 'utf-8').match(/<button\b[^>]*>/g) ?? [];
      for (const tag of tags) {
        if (!/\btype\s*=/.test(tag)) {
          offenders.push(`${path.relative(srcRoot, file)}: ${tag.replace(/\s+/g, ' ')}`);
        }
      }
    }

    expect(
      offenders,
      `以下 <button> 缺少 type="button"，在 <el-form> 内点击会触发表单提交并整页刷新：\n${offenders.join('\n')}`,
    ).toEqual([]);
  });
});
