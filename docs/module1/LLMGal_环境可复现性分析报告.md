# LLMGal 环境可复现性分析报告

> 问题：能否直接在项目中建好 Python 环境与依赖项，让拿到项目的人直接上手运行？
>
> 结论日期：2026-09-14　分析对象：`F:\LLMGal`（分支 `main`，HEAD `4e9806f`）

---

## 一、结论

**部分可行，但不能用「把环境打进仓库」的方式实现。**

| 目标 | 可行性 | 依据 |
| --- | --- | --- |
| 目标机一键装出后端环境 | **可行**（需改 1 行依赖） | 72 条依赖中仅 1 条无法安装，已实测 |
| 目标机一键装出前端环境 | **可行** | `frontend/package-lock.json` 已入库，`npm ci` 可确定性复现 |
| 零密钥跑通 34 条后端测试 | **已基本达成** | `scripts/run_module1_tests.sh` 自带解释器探测 + 依赖自愈 |
| 零密钥跑通完整应用 | **不可行，且不应追求** | 设计上必须有三类外部服务凭据 |
| 把 `.venv` 直接放进仓库分发 | **不可行** | Python venv 不可重定位，见 §3.2 |
| 用 Docker 彻底隔离环境 | 可行，但对本项目收益有限 | 见 §4.3 |

一句话因果链：**依赖本身是「可复现」的，环境是「不可搬运」的，密钥是「不可分发」的。** 所以正确做法不是"建好环境塞进仓库"，而是**在仓库里放一个能在目标机自动建出环境的自举脚本**，并保证脚本在任何一台干净机器上都能跑通。

---

## 二、现状体检（实测证据）

### 2.1 仓库卫生：好消息

| 项目 | 实测结果 | 判定 |
| --- | --- | --- |
| `git` 跟踪文件总数 | 179 个（frontend 134 / backend 30） | 轻量，合理 |
| `frontend/node_modules`（248 MB） | **未被跟踪** | ✓ 正确 |
| `.venv-module1`（53 MB） | **未被跟踪**，已在根 `.gitignore` 中 | ✓ 正确 |
| 工作区总体积 | 387 MB，其中 `.git` 仅 26 MB | ✓ 健康 |
| 数据库/Redis 相关依赖 | 无任何代码 `import` | 见 §2.3 |

### 2.2 依赖清单严重注水

`backend/requirements.txt` 共 **72 条**，但后端代码真实 `import` 的第三方运行时依赖只有 **8 个**：

```
fastapi  starlette  pydantic  uvicorn  websockets  requests  openai  volcengine
```

（测试另需 `pytest` / `pytest-asyncio` / `pytest-cov` 3 个，已单独放在 `requirements-test.txt`。）

清单里的大头是**从其它项目环境整份 `pip freeze` 导出的无关包**，证据：

- `Flask==3.1.1` 及整套 Flask 生态：`blinker`、`itsdangerous`、`Jinja2`、`MarkupSafe`、`Werkzeug` —— 本项目是 FastAPI，零使用。
- `mysqlclient`、`PyMySQL`、`SQLAlchemy==2.0.9`、`redis==4.5.4`、`redis-om`、`hiredis` —— 项目无数据库、无 Redis。
- `google`、`beautifulsoup4`、`soupsieve`、`pptree`、`tqdm`、`more-itertools`、`py` —— 与项目无关。
- `websocat==1.13.0` —— 这是个**命令行工具**，不是 Python 库，被冻进了依赖表。
- `python-dotenv` —— `config.py` 明确注释「避免为此引入额外依赖」，自己实现了 `.env` 解析，实际不依赖它。

**约 85% 的依赖条目是冗余的。** 后果不是"装不上"，而是：安装时间被拉长、攻击面变大、其中一个包恰恰就是装不上的那个（见 §3.1）。

### 2.3 依赖可安装性：实测结果

对全部高风险包逐个查询 PyPI 分发元数据，并在干净 3.11 venv 中实测安装：

| 包 | Windows/cp311 预编译轮子 | 结论 |
| --- | --- | --- |
| `pycryptodome==3.9.9` | **无**（win_amd64 轮子最高到 cp39） | **安装失败**（实测） |
| `mysqlclient==2.1.1` | 有 `cp311-cp311-win_amd64` | 可装 |
| `cryptography==40.0.2` | 有 `cp36-abi3-win_amd64`（abi3 向上兼容） | 可装 |
| `watchfiles==0.19.0` | 有 `cp37-abi3-win_amd64` | 可装 |
| `hiredis==2.2.2` | 有 `cp311-cp311-win_amd64` | 可装 |
| `httptools==0.5.0` | 有 `cp311-cp311-win_amd64` | 可装 |
| `cffi==1.15.1` | 有 `cp311-cp311-win_amd64` | 可装 |
| `greenlet==2.0.2` | 有 `cp311-cp311-win_amd64` | 可装 |
| `volcengine==1.0.192` | 无轮子，但为纯 Python 源码包 | 可装（本机构建，不需编译器） |
| `websocat==1.13.0` | 有 `py3-none-win_amd64` | 可装 |

**失败实测原文：**

```
ERROR: Could not build wheels for pycryptodome, which is required to install pyproject.toml-based projects
  error: Microsoft Visual C++ 14.0 or greater is required.
```

---

## 三、三个真正的阻塞点

### 3.1 阻塞点一：`pycryptodome==3.9.9` 硬失败（P0，一行可修）

**成因**：该版本发布于 2020-11，而 Python 3.11 发布于 2022-10，官方从未为 cp311 提供 Windows 轮子。钉死版本号 `==3.9.9` 后，`pip` 只能回退源码编译，要求目标机装有 MSVC 14.0+ Build Tools —— 而这恰恰是"拿到项目的人"最不可能预先具备的东西。

**影响**：`pip install -r requirements.txt` 在最后一步整体失败，**所有依赖都装不上**，一键脚本直接死掉。

**处置**：`pycryptodome` 并非本项目的真实依赖（后端无任何 `import Crypto`），它是 `volcengine` SDK 的传递依赖。两条路：

- 删掉该行，让 `pip` 自行解析 `volcengine` 的需求（会装到有轮子的新版本）；
- 或把它钉到 3.20+（有 cp311 Windows 轮子）。

### 3.2 阻塞点二：虚拟环境不可「打包分发」（P0，架构级）

`F:\LLMGal\.venv-module1\pyvenv.cfg` 的实际内容：

```ini
home = E:\Anaconda\envs\vue-fastapi
executable = E:\Anaconda\envs\vue-fastapi\python.exe
command = E:\Anaconda\envs\vue-fastapi\python.exe -m venv F:\LLMGal\.venv-module1
version = 3.11.13
```

**venv 里烧死了本机绝对路径。** 这不是配置疏忽，是 Python 官方设计行为：venv 内的解释器依赖 `home` 指向的基础环境与 `python311.dll`。目标机上不存在 `E:\Anaconda\envs\vue-fastapi`，解释器直接启动失败；即使能启动，`Lib\site-packages` 下的 `.pyd` 二进制扩展也是与本机 ABI 绑定的。

**结论**：任何"把 venv 目录压缩发出去"的思路都是死路。**环境必须在目标机上重新生成。**

### 3.3 阻塞点三：密钥与配置的三种状态混乱（P0，安全）

实测发现三个不同的问题叠在一起：

**(a) 真密钥已进入版本历史。** 以下文件**已被 git 跟踪**，且密钥来自 `Initial commit`（`ecf4292`），当前仍在 `main` 上：

| 文件 | 内容 |
| --- | --- |
| `backend/image_emotions.py:4-5` | 火山引擎 `ACCESS` / `SECRET` 硬编码 |
| `backend/TestSubject2.py:8-9` | 同一组 `ACCESS` / `SECRET` |
| `backend/tts_websocket_demo.py:24` | 火山 `appid = "7535590105"` |

`config.py` 的注释显示 `Text.py` / `Voice.py` / `Image.py` 的硬编码已修复，但**这三个遗留脚本被漏掉了**。由于密钥已进历史，**即使现在删除文件内容也不算修复，必须在火山控制台轮换该 AccessKey 对**。

**(b) `backend/.env` 未受保护。** 根 `.gitignore` 中**没有** `.env` 规则，实测 `git check-ignore backend/.env` 返回未忽略，`git status` 中它显示为 `??`。当前没进仓库，纯粹因为从没人执行过 `git add .`。**任何一次 `git add .` 都会把真实密钥直接推上去。**

**(c) 配置模板根本没入库 —— 这是个被忽略的死结。** `git status` 显示：

```
?? backend/.env.example
?? frontend/.env.example
```

两个 `.env.example` 都是**未跟踪状态**。而 `README.md` 第 73 行明确引导用户"复制 `.env.example` 为 `.env`"。**新克隆仓库的人根本找不到这个文件。** 这条引导链在仓库层面是断的。

---

## 四、三条实现路线对比

### 4.1 路线 A：加固现有自举脚本（推荐）

`scripts/run_module1_tests.sh` 已经是一个**相当成熟的环境自举器**，它已经正确处理了本机的三个坑：解释器探测（`python3.11` / `py -3.11` / `python3`）、venv 双布局（`bin/` 与 `Scripts/`）、MSYS 路径转换（`cygpath -m`）、依赖自愈、版本断言（拒绝非 3.11）。

它缺的是三块：

| 缺口 | 具体表现 | 补法 |
| --- | --- | --- |
| 只装测试依赖 | 只装 `requirements-test.txt`（7 条），跑不起应用 | 增加 `--full` 模式装 `requirements.txt` |
| Windows 入口缺失 | 只有 `.sh`，双击不可用，依赖 Git Bash | 加 `setup.bat` / `setup.ps1` 薄封装 |
| 依赖表注水 | 装 72 个包里有 63 个用不上 | 拆出 `requirements-core.txt`（8 条） |

**成本**：半天以内。**收益**：目标机 `git clone` 后一条命令跑通测试，两条命令跑起应用。

### 4.2 路线 B：引入锁文件工具（`uv` / `pip-tools`）

用 `uv` 替代 `venv + pip`：它可以依据 `pyproject.toml` 自动下载**指定版本的 CPython 解释器**，目标机不需要预装 Python 3.11 —— 这直接消除了本项目最烦的一环（必须凑出 3.11，而 3.12/3.13 会让 `fastapi 0.95.1 + pydantic 1.10.7` 在收集阶段就崩）。

**成本**：1～2 天（需要迁移依赖声明、验证 lock）。**收益**：跨平台一致性最好，且安装速度通常快 5～10 倍。

### 4.3 路线 C：Docker

最彻底，但对本项目**收益不对等**：

- 前端仍需 `npm ci` 并连宿主后端，容器化只包住一半；
- 开发期要频繁改 `backend/*.py` 并重启，容器内编辑体验差；
- 目标机要装 Docker Desktop（Windows 上装它比装 Python 3.11 更重）；
- 本项目依赖全是纯 Python 或现成轮子，没有"环境难搭"的原罪。

**建议**：现阶段不采用。

---

## 五、建议动作清单

按优先级排列，前四项是"让别人能跑起来"的硬前提：

| # | 动作 | 类型 | 阻塞什么 |
| --- | --- | --- | --- |
| 1 | **轮换火山 AccessKey 对**，清理 `image_emotions.py` / `TestSubject2.py` / `tts_websocket_demo.py` 中的硬编码 | 安全 | 任何形式的分发 |
| 2 | 根 `.gitignore` 增加 `.env`、`.env.local` 规则 | 安全 | 误提交密钥 |
| 3 | **把两个 `.env.example` 加入 git**（当前未跟踪） | 可用性 | README 的引导链 |
| 4 | 修 `pycryptodome==3.9.9`（删除或升版） | 可用性 | 后端依赖安装整体失败 |
| 5 | 拆出 `requirements-core.txt`（8 条运行时依赖） | 效率 | 安装耗时与攻击面 |
| 6 | 补 `setup.bat` / `setup.ps1` | 可用性 | Windows 用户双击上手 |
| 7 | 修 README 快速开始里的 `python3.11`（Windows 不存在该命令） | 文档 | 按文档操作必失败 |
| 8 | 统一环境目录命名（README 用 `.venv`，脚本用 `.venv-module1`） | 文档 | 认知混淆 |

### 关于"零密钥直接上手"的边界

需要明确一点：**完整应用的运行无法零密钥复现，这是设计使然，也不该被消除。**

`config.py` 的 `missing_credentials()` 会在缺密钥时给出明确报错而不是静默失败——这是正确的工程决策。要把密钥"打包进去"，只有两种可能：把作者的私有 key 发给所有人（安全事故），或预置共用公共 key（费用与滥用风险）。

因此合理的可复现性目标应定为两档：

- **档位一（应当做到，当前已接近达成）**：`git clone` → 一条命令 → 34 条后端测试 + 1 条前端测试全绿。**全程不需要任何密钥**（`conftest.py` 会阻断所有真实网络调用，并对漏网的调用直接判失败）。
- **档位二（应当做到）**：填好 `.env` 后 `git clone` → 两条命令 → 前后端跑起来。**密钥由使用者自备**，README 已给出三家免费额度渠道（智谱 / 阿里百炼）。

---

## 附录：证据清单

所有结论均来自本地实测，可复现：

```
# 依赖注入与安全
git ls-files                                  # 179 个跟踪文件
git check-ignore -v backend/.env              # 返回未忽略
git status --porcelain                        # .env.example 为 ?? 状态
git log --oneline -S "AKLTODlhZDdk..." --all  # ecf4292 Initial commit

# venv 可移植性
cat .venv-module1/pyvenv.cfg                  # home = E:\Anaconda\envs\vue-fastapi

# pycryptodome 实测（干净 3.11 venv）
pip install --no-cache-dir pycryptodome==3.9.9
# -> ERROR: Could not build wheels ... Microsoft Visual C++ 14.0 or greater is required

# PyPI 分发元数据批量核对
https://pypi.org/pypi/{包名}/{版本}/json       # 逐包比对 win_amd64 轮子
```

**本轮分析未修改仓库内任何文件。** 期间在 `F:\f\` 误建过一个临时 venv（MSYS 路径转换导致，26 MB），以及系统 `Temp` 下的探测脚本，均已清理，项目根目录未受污染。
