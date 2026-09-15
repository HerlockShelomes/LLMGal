# 本次修复与工作区恢复说明（2026-09-14 夜）

## 一、工作区被自动 stash 的问题（已解决）

21:31 在 GitHub Desktop 里切分支，当时工作区有一大批**未提交**改动，
GitHub Desktop 按惯例自动 stash（带 `-u`，连未跟踪文件一起收走），
工作区瞬间回到旧提交状态，并且之后**再切分支被它拦住**
（报 “commit your changes or stash them before you switch branches”）。

`stash@{0}` = `39093bf`，**138 文件 / +14050 行**，包含：

- 本项目**全部**功能代码：创建角色、删除角色、Mock/正式版切换、图片风格统一、
  音频与静态资源三级回退、角色清点对账等；
- 本次两个 bug 的修复；
- 本次新增的测试 `backend/tests/test_role_list_cases.py`、`frontend/src/_tests_/roleReconcile.test.ts`；
- `artifacts/` 下的探针脚本与出图证据（`style_before.jpg` / `style_after.jpg` /
  `style_unified_base.jpg` / `style_unified_emotion.jpg`）；
- `pictures/林亦/`、`roles/林亦.txt`、`voice/林亦/`（新建的「林亦」角色的全部文件）。

### 实际做过什么（顺序）

1. 卡住的原因不是普通「有未提交改动」，而是索引里有 **5 个 `backend/__pycache__/*.pyc` 处于未合并状态**
   （stash 冲突残留，stage 1/2/3）。`git ls-files -u` 能看到，GitHub Desktop 只会笼统报「先提交或 stash」。
2. `git checkout HEAD -- backend/__pycache__/xxx.pyc` 逐个消掉未合并条目。
3. `git reset` 把索引清干净（此时已无 `UU` 条目，`git diff --diff-filter=U` 为空）。
4. `git checkout main` —— 切换成功。
5. `git stash apply 'stash@{0}'`（**用 apply 不用 pop**：失败时 stash 还在，可重来）。
   第一次 apply 被拒：有 4 个未跟踪文件会被覆盖
   （`.workbuddy/memory/2026-09-14.md`、`MEMORY.md`、`artifacts/build_fix2.log`、`artifacts/build_roledelete.log`）。
   把这 4 个先挪到 `F:\LLMGal\artifacts\_prestash_backup\`，再 apply → 成功。
6. 用备份里的新版覆盖回 stash 里的旧版记忆文件。

### 收工状态

| 项 | 值 |
|---|---|
| 当前分支 | `main`（`37d2c2a`，比 `origin/main` 落后 5 个提交） |
| 未合并条目 | 0（`git ls-files -u` 空） |
| 工作区改动 | **153 条**（108 条已入索引 + 30 条已改未暂存 + 15 条未跟踪） |
| `stash@{0}` | **仍然保留**（故意不 pop，留作兜底） |
| 另有一个 | `stash@{1}: On testificate_fxy: !!GitHub_Desktop<testificate_fxy>` |

注意：`testificate_fxy` 是 `main` 的**祖先**（`main...testificate_fxy` = `11 0`），
即它一个提交都没多，只是旧分支。所以改动落回 `main` 是对的。

`stash@{0}` 里包含的内容（已逐项核对）：

- 本项目**全部**功能代码：创建角色、删除角色、Mock/正式版切换、图片风格统一、
  音频与静态资源三级回退、角色清点对账等；
- 本次两个 bug 的修复；
- 本次新增的测试 `backend/tests/test_role_list_cases.py`、`frontend/src/_tests_/roleReconcile.test.ts`；
- `artifacts/` 下的探针脚本与出图证据（`style_before.jpg` / `style_after.jpg` /
  `style_unified_base.jpg` / `style_unified_emotion.jpg`）；
- `pictures/林亦/`、`roles/林亦.txt`、`voice/林亦/`（新建的「林亦」角色的全部文件）。

### 下一步建议（需要你自己决定）

现在 `main` 上挂着 153 条未提交改动，**再切分支 GitHub Desktop 还会拦你**。三个选项：

- **提交**（推荐）：在 `main` 上 commit。注意 `git commit` 不带 `-a` 只会提交已入索引的
  108 条，剩下 30 条改动 + 15 条未跟踪要 `git add -A` 才进得去。
- **建新分支承接**：`git switch -c <名字>` 后提交，把「功能开发」和 `main` 的稳定线分开。
- **先不提交**：那就别切分支；`stash@{0}` 一直在，随时能再 apply。

我没有做任何 `git commit` / `git push`（这是既定约定），停在这里等你指令。

## 二、两个 bug 的根因与修复

### 1. 点删除按钮后页面自己刷新

**根因**：删除按钮写成裸 `<button>`，而它落在 `<el-form>` 里。
Element Plus 的 `el-form` 渲染出的就是原生 `<form>`
（源码 `node_modules/element-plus/es/components/form/src/form2.mjs`：
`createElementBlock("form", {...}, [renderSlot(...)])`）。
原生 `<button>` 缺省 `type` 是 `submit` → 点下去表单提交 → 整页刷新 →
确认弹窗根本来不及出现。

**修复**：`frontend/src/components/SettingsPanel.vue` 里 4 处原生 `<button>` 全部补 `type="button"`。
（只有删除按钮真的在 form 内，其余 3 处一并补上，避免以后挪位置再犯。）

这类缺陷**编译、类型检查、单测全都发现不了**（不报错、不抛异常，只是页面重载），
因此补了一条模板守卫测试：递归扫描 `frontend/src/**/*.vue`，任何原生 `<button>` 缺 `type` 即失败。

### 2. 林彻「没删掉」

**根因**：磁盘上其实早就删干净了 —— 全仓搜索「林彻」文件/目录名 0 命中、
`Records.txt` 无该段、`custom_role_voices.json` 为空。
界面还在，是因为角色下拉列表 = 内置角色 + `store.customRoles`，
而 `customRoles` 持久化在 **localStorage**（key `ai-chat-settings`）。
删除流程被上一条的页面刷新打断，`purgeRole()` 从未执行，缓存里就留下一个
磁盘上已不存在的**幽灵角色**：它还能点删除，但点了又刷新，看起来就是「删不掉」。

**修复**：让前端缓存跟后端磁盘对账，刷新即自愈。

- 后端新增 `Create_New_Role.list_custom_roles()`：六路探针取并集
  （`custom_role_voices.json` 键、`roles/*.txt`、`Role_Description/*.txt`、
  `pictures/<角色>/`、`pictures/temp/<角色>_<idx>.jpg`、`voice/<角色>/` 与 `voice/_mock/<角色>/`），
  再减去内置角色与内部目录（`Role_Description` / `temp` / `_samples` / `_mock`）。
  **探针范围刻意与 `delete_role()` 的清理范围一一对应** —— 两边一漂移就会出现
  「删了但清单里还在」或「清单说还在、其实文件早没了」两种不报错的假象。
- 后端新增 `GET /api/roles/list` → `{"roles": [...]}`（出错返回 502，不把异常抛给客户端）。
- 前端新增 `utils/roleCreation.ts::reconcileCustomRoles()`，挂在 `ChatView` 挂载时执行
  （紧跟原有的 `reconcileCreatingRoles`）。安全约束：请求失败 / 非 2xx / `roles` 不是数组
  → **一个都不动**（宁可留脏数据也不能误清用户角色）；「创建中」的角色跳过
  （此刻文件还没落齐，按磁盘判断必然误判）。
- 真实仓库实测：`list_custom_roles()` → `["林亦"]`；`GET /api/roles/list` → `200 {"roles":["林亦"]}`。
  即刷新后「林彻」会自动从下拉框消失，并弹一条提示说明清了哪几个。

### 3. 顺手修掉的第三处隐患（同一个删除流程里）

`frontend/vite.config.ts` 的 `server.watch.ignored` 只挡住了
`src/assets/voice/**` 和 `src/assets/pictures/**`，**漏了 `src/assets/roles/**`**。
而 `roles/*.txt` 同样被 `import.meta.glob(..., {eager: true})` 静态引用 ——
删除角色会删掉 `roles/<角色>.txt`，文件一消失 Vite 判定该 glob 模块失效、直接整页重载，
会把刚弹出的成功提示一起刷掉。已补上 `'**/src/assets/roles/**'`。

## 三、验证结果

| 项 | 结果 |
|---|---|
| 后端 `pytest -q` | **124 passed**（113 → +11，新增 `test_role_list_cases.py` TC-LIST-01..11） |
| 前端 `npm run test -- --run` | **23 passed / 5 files**（16 → +7：6 条对账用例 + 1 条模板守卫） |
| 前端 `npm run build`（含 `vue-tsc -b`） | **EXIT 0**，`built in 18.78s`，产物 `index-D5VSsdVY.js` 2.54 MB |
| 全项目裸 `<button>` 预检 | 7 个 `.vue`，缺 `type` 的 **0 条** |
| 真实 `GET /api/roles/list` | `200 {"roles":["林亦"]}` |

构建产物里 `林亦_*.jpg` / `林亦_*_Stream.wav` 齐全（9 张图 + 2 段音频）、
**「林彻」零残留** —— 删除确实生效了。
