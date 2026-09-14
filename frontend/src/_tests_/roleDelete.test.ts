import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';

import { defaultRole, getImageUrl, useSettingsStore } from '../stores/settings';

/**
 * 删除角色时的前端状态清理（purgeRole）。
 *
 * 关键点：角色名是出图 / 音频 / 人设三处的索引键。删掉角色后若 RoleConfig.roleName
 * 还指着它，界面就会去取一堆已经被删掉的文件 —— 图片走 <img> 报错、人设 fetch 404、
 * 语音候选全空。所以「删掉的正是当前选中角色」时必须同步回退到内置默认角色。
 */

const ROLE = '林彻';

describe('purgeRole', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('把角色从「列表 / 详情 / 创建中」三处一并清掉', () => {
    const store = useSettingsStore();
    store.addNewRole({ label: ROLE, value: ROLE, type: '虚拟角色' });
    store.setCustomRoleDetail(ROLE, {
      personality: '温柔沉稳',
      voiceId: 'Mia',
      imageDescription: 'black hair',
    });
    store.addCreatingRole(ROLE);

    store.purgeRole(ROLE);

    expect(store.customRoles.some(r => r.value === ROLE)).toBe(false);
    expect(store.customRoleDetails[ROLE]).toBeUndefined();
    expect(store.creatingRoles).not.toContain(ROLE);
  });

  it('删除的正是当前选中角色时，回退到内置默认角色', () => {
    const store = useSettingsStore();
    store.addNewRole({ label: ROLE, value: ROLE, type: '虚拟角色' });
    store.RoleConfig.roleName = ROLE;

    store.purgeRole(ROLE);

    expect(store.RoleConfig.roleName).toBe(defaultRole[0].value);
    expect(store.RoleConfig.roleImage).toBe(getImageUrl(defaultRole[0].value, 'neutral'));
  });

  it('删除的是别的角色时，不动当前选择', () => {
    const store = useSettingsStore();
    store.addNewRole({ label: ROLE, value: ROLE, type: '虚拟角色' });
    store.RoleConfig.roleName = 'Wendy';

    store.purgeRole(ROLE);

    expect(store.RoleConfig.roleName).toBe('Wendy');
    expect(store.customRoles.some(r => r.value === ROLE)).toBe(false);
  });
});
