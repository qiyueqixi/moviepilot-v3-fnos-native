# MoviePilot V3 飞牛原生 FPK

独立的 MoviePilot **3.2.3-5** 安装包工程，目标为 fnOS 1.2.0 及以上的 x86_64 / ARM64 设备。采用原生 Python 和 Node.js 服务运行。

## 与 V2 同时安装

| 项目 | 本工程 V3 | 现有 V2 |
| --- | --- | --- |
| 应用 ID / 包用户 | `moviepilot-v3` | `moviepilot` |
| 桌面名称 | MoviePilot V3 | MoviePilot |
| 访问路径 | `/app/moviepilot-v3/` | `/app/moviepilot/` |
| 后台监听 | `127.0.0.1:3101` | `127.0.0.1:3001` |
| 应用文件 | `moviepilot-v3/config` 等 | `moviepilot/config` 等 |
| 私有运行数据 | `${TRIM_PKGVAR}`，属于 V3 应用 | 属于 V2 应用 |
| 浏览器存储前缀 | `moviepilot-v3:` | 沿用 V2 |
| 资源 Cookie | `MoviePilotV3` | `MoviePilot` |
| Python | 内置独立 3.14.10 | 3.11 |

V3 新建自己的配置和数据库。安装 V3 时无需卸载 V2；两者不自动同步配置。卸载清理限定在 `moviepilot-v3` 自己的目录。

## 安装

构建产物在 `dist/`：

- `moviepilot-v3_3.2.3-5_x86.fpk`：x86 完整离线包。
- `moviepilot-v3_3.2.3-5_arm.fpk`：ARM64 完整离线包。
- 文件名带 `_installer` 的包：拆分安装包，需要同批次对应架构的运行时。
- `moviepilot-v3-runtime-{x86|arm}-python314.tgz`：拆分运行时。
- `SHA256SUMS.txt`：产物校验值。
- `BUILD_INFO.json`：上游版本、源码提交和下载输入哈希。

在飞牛应用中心选择本地安装并上传与设备架构对应的完整 FPK。安装后，在应用设置中授权媒体库、下载目录，再从飞牛桌面的 **MoviePilot V3** 进入。

拆分安装：先安装 `_installer.fpk`，把对应的运行时 `.tgz` 原样上传到应用文件的 `moviepilot-v3/runtime` 目录，再启动。运行时会校验与安装包匹配的 SHA-256。

首次启动会在新数据库建立真实的管理员账号，由飞牛网关提供登录保护；进入应用无需再次输入 MoviePilot 密码。站点认证仍需在 MoviePilot 中完成，等级使用上游真实认证结果。

启动页会等待 `/health/ready` 返回成功；初始化失败可查看应用文件 `logs/moviepilot-v3.log`。支持在 `config/` 放置 `loading-background.jpg` 等背景图片。

## 安装、升级与卸载

按飞牛应用目录规范使用系统提供的映射，不依赖 `/home/moviepilot-v3` 或固定磁盘编号：

| 用途 | fnOS 环境变量 / 目录 |
| --- | --- |
| 程序及内置资源 | `TRIM_APPDEST`，系统 `target` 映射 |
| 持久运行数据、Python 环境 | `TRIM_PKGVAR`，系统 `var` 映射 |
| 用户主目录 | `TRIM_PKGHOME`，系统 `home` 映射 |
| XDG 与浏览器缓存 | `${TRIM_PKGHOME}/.cache` |
| 临时文件 | `TRIM_PKGTMP`，系统 `tmp` 映射 |
| 用户可见配置、日志、导出和运行时上传 | `config/resource` 声明，通过 `TRIM_DATA_SHARE_PATHS` 获取 |

从 3.2.3-3 升级时会把旧私有 home/cache 复制到映射目录，不覆盖已存在的新文件，旧副本保留供恢复。

完整包安装时初始化独立数据目录，校验并解压匹配的运行时；拆分包允许先安装，上传运行时后再启动。安装出错会返回失败并在飞牛安装提示中记录原因，可保留数据后重试。

升级前完整停止 V3 服务，升级后安装匹配的运行时，保留现有配置和数据库。卸载向导默认选择保留数据，重装可继续使用；明确选择删除时，仅清理 V3 的配置、数据库、日志、导出文件、运行时和私有应用数据。媒体库、下载目录及 V2 数据保留。删除前校验所有目标的真实路径，发现异常或指向其他目录的符号链接则停止卸载。

## 已适配

- V3 的认证依赖、资源令牌、首次管理员初始化与真实用户 ID。
- V3 的原子文件复制、引用链接和文件代理，外加 fnOS 授权目录检查；每次操作重新校验真实路径。
- HTTP、SSE 和 WebSocket 经 Unix Socket 接入飞牛统一网关。
- 本地存储、Cookie、端口、数据目录与 V2 分离。
- 应用内部重启由原生后台管理脚本处理。
- 更新通过新 FPK 安装；应用内部更新接口会提示使用飞牛应用中心。
- 内置标准 CPython 3.14.10、锁定 Python 依赖、Node.js 22.21.1、V3 站点资源与中文 FTS 扩展。

## 验证范围

本地覆盖授权目录、越权读写、符号链接逃逸、授权撤销、V2/V3 浏览器状态隔离、网关路由、就绪状态、SSE 和 WebSocket。Windows 下使用 Python 3.14 实际启动 V3 安全模式，验证首次管理员建立、真实用户查询、Cookie 范围、重启后的用户持久化和更新限制。Python 源码使用 3.14 检查，打包时校验 Linux 二进制架构及 glibc 版本。

当前产物是**待实机验证版本**：尚未在 fnOS 上完成安装与业务验证。包内不包含 Chromium 浏览器和 ffmpeg/rclone 等可选系统工具；依赖这些工具的浏览器认证、媒体处理、云盘挂载功能需要另行提供对应环境。核心界面、订阅、下载和整理的实际可用性以实机验证为准。

## 开发与构建

GitHub 私有仓库：[moviepilot-v3-fnos-native](https://github.com/qiyueqixi/moviepilot-v3-fnos-native)。
`Upstream V3 native FPK` 工作流每 6 小时检查稳定版 V3，也支持在 Actions 页面手动指定版本及重建草稿。
后端声明的前端版本、源码提交、站点资源提交会在一次检查中锁定，两个架构共用同一份输入；不跟随 V2、V4 或预发布版。
若 Python 要求改变、补丁失配、代理源码发生额外改写、依赖导入或启动测试失败，流程停止，不生成新版 Release。

构建机分别在 x86 和 ARM 上从实际安装包提取源码与 Python 运行时，验证 Linux 原生模块、SQLite 中文扩展、安全模式启动、真实用户持久化、Cookie、重启和更新限制。
两种架构都通过后上传 **Release 草稿**，附完整包、拆分包、运行时、来源和校验报告；设备仍由用户手动升级。定时构建在 GitHub 运行，本地电脑关机不影响。
`upstream.json` 是构建基线；每次 Release 的 `BUILD_INFO.json` 记录当次实际锁定的上游输入。适配代码变化时应增加 `native_revision`。

`upstream.json` 固定后端 / 前端版本、后端与站点资源提交、Python 和 Node 版本。V3 使用上游 `uv.lock` 的 `runtime-standard` 依赖组。

工具：Python 3.13+、Git、Node.js/npm、uv 0.13.6 和支持交叉编译的 Zig。运行时目标为 Debian 12 / glibc 2.36；Python 使用 python-build-standalone 的可重定位版本，Zig 以 glibc 2.28 为中文扩展的构建基线。

```powershell
python scripts/build-v3.py --platform all --uv <uv路径> --zig <zig路径>
python scripts/test-native.py
node scripts/test-session.cjs
node scripts/test-gateway.cjs
python scripts/verify-packages.py
```

脚本会生成完整包、拆分包与独立运行时。首次构建下载输入到 `.build/downloads/`；重建可使用 `--reuse-runtime` 复用已完成的运行时。只有依赖、Python 或中文扩展输入均未变化时才使用此选项。

目录：

- `fnos/`：manifest、权限 / 资源声明、生命周期、桌面入口与原生适配。
- `scripts/patch-v3.py`：匹配失败立即停止的 V3 专用补丁，可重复执行。
- `scripts/build-v3.py`：准备上游、组装运行时并打包。
- `.reference/`：本地参考仓库，不进入包和源码提交。
- `.build/`：构建缓存，不进入源码提交。

飞牛规范参考：[ckcoding/fnnas-docs](https://github.com/ckcoding/fnnas-docs)。V2 基础工程来自 [moviepilot-fnos-native](https://github.com/qiyueqixi/moviepilot-fnos-native)；上游应用来自 [MoviePilot](https://github.com/jxxghp/MoviePilot)。
