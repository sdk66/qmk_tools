# QMK Firmware Studio

面向 **WB32FQ95 / QMK Raw HID** 的离线升级包制作工具。制作端包含固件、APP 参数、发布设置及深色的发布文件预览。客户页约 **650 × 550**，采用紧凑进度条和日志布局，保留“让键盘，焕然一新。”和“连接 USB 数据线，剩下的交给我们。”。背景默认白色，可选浅蓝、暖白或深色；背景选择仅改变客户升级页，制作页及发布预览保持一致的深色面板。

输出名称默认来自所选 HEX/BIN 的文件名并加 `_update`，例如 `mk20b_via_v9.hex` → `mk20b_via_v9_update.exe`。名称可单独编辑，不随设备名称、版本或烧录模式变化。匹配、进 Boot 和 Flash 预检查阶段均保持 0%，仅在页面写入和校验后增加百分比。退出 DFU 只发送一次命令，完成日志合并为一次结果。

制作工具左上角显示 **v1.0.0**。右上角「界面背景」提供深色、粉色、黄色、蓝色、绿色、青色、紫色、白色，默认蓝色，发布预览同步配色。客户升级页背景使用发布设置中的独立选项，保持默认白色。显示版本与内部运行模板兼容版本分离，既有运行模板 API 和烧录行为保持不变。

勾选「打开后自动开始」时，客户双击后识别键盘即升级；取消勾选时，连接键盘后需点击开始按钮。单次与工厂连续烧录均可使用。

## 现在可以使用的文件

- `release/windows-x64/QMK-Firmware-Studio.exe`：Windows 制作端，也可以作为原生升级运行模板。
- `release/windows-x64/mk20b_via_v9_update.exe`：单次客户包。双击后自动识别升级，成功并确认重连后，倒计时 5 秒关闭。
- `release/windows-x64/factory/mk20b_via_v9_update.exe`：工厂连续烧录包。与单次示例分目录保存，成功后等待更换下一把，显示成功/失败计数，支持暂停。
- `examples/SAMURAI-S751-v0.0.9.qmk`：通用固件数据包，含固件段、参数及 SHA-256。
- `release/windows-x64.qmk-runtime.zip`：本次 Windows 构建导出的可导入运行模板。
- `release/QMK-All-System-Templates.zip`：已完成原生构建、启动检查的四系统运行模板集合。
- `release/macos-arm64/mk20b_via_v9_update.zip`、`release/macos-x64/mk20b_via_v9_update.zip`：在 Windows 装包的真实 Mac 示例升级包。
- `release/linux-x64/mk20b_via_v9_update.tar.gz`：在 Windows 装包的 Linux 示例升级包。
- `maker-preview.png`、`updater-preview.png`、`factory-preview.png`：实际 Qt 界面截图。

**验证范围：** 四系统运行模板已在各自原生 GitHub runner 构建，通过自动化测试、冻结程序启动和安全预览检查；Mac 解压后的应用另通过 `codesign --verify --deep --strict`。Windows 工具已装入四平台模板，可直接选择目标系统。没有对实物键盘发送进 Boot / 擦除 / 写入命令，也没有在 Windows 7 真机运行。Mac 正式对外分发仍需要厂家的 Developer ID 签名和公证。

## 制作升级包

1. 打开制作端，拖入 `.hex` 或 `.bin`。HEX 校验每条记录的校验和、地址、重叠、结束记录和 ARM 向量表；BIN 需填写实际烧录地址，默认 `08000000`。
2. USB 和 Raw HID 描述符只有一组时自动填入；多组时在「高级参数」中选择。未识别到的项目允许手动配置，但生成前会提示确认。
3. 确认 APP 的 VID、PID、Usage Page、Usage ID。这些是**客户当前旧固件**的参数，可以与新固件不同。默认值来自新固件，旧固件不同则必须修改。
4. Boot 默认 `342D:DFA0`，Raw HID 默认 32 字节、Report ID `00`。Boot 标识、报告参数和 APP/BIN 地址收在「高级参数」中。APP 与手动 DFU 两种入口始终同时可用，不需要额外开关；`0x0B` 固定为 VIA Boot 跳转命令。
5. 编辑设备名称、版本及独立的「升级包文件名」，选择客户系统、单次/连续模式、「打开后自动开始」及升级页背景，再点击「生成升级包」。文件名初始值取 HEX/BIN 去掉扩展名再加 `_update`；系统后缀自动补齐。右侧发布预览与制作页同步配色，只显示实际输出名称、系统、模式及启动方式。

## Windows 上生成 Mac / Linux 升级包

**可以在 Windows 制作工具中生成 Mac 或 Linux 客户包。** 运行模板首次在对应系统构建一次，之后每次更换固件、设备参数、背景或烧录模式，都可以在 Windows 离线装包。下拉框明确显示 Windows、macOS Apple Silicon、macOS Intel 和 Linux，不再使用「本机原生」字样。

1. 完整 Windows 工具包已经在旁边 `templates/` 附带四系统真实模板。直接打开目录中的制作工具，选择目标系统即可。
2. 如果只复制了单独 EXE，点击「导入模板」，选择对应 `*.qmk-runtime.zip` 或 `QMK-All-System-Templates.zip`。工具校验模板 API 版本、文件完整性和实际 PE / Mach-O / ELF 架构。
3. 选择目标系统，显示「模板已就绪」后即可生成。没有该系统模板时会明确显示待导入，不会生成伪装的文件。

| 客户系统 | 输出 | 客户操作 |
| --- | --- | --- |
| Windows 7 / 10 / 11 x64 | `.exe` | 双击运行 |
| macOS Apple Silicon / Intel | `.zip` | 解压完整文件夹，双击其中的 `.app` |
| Linux x64 | `.tar.gz` | 解压后运行，归档中保留可执行权限 |

Mac 包保留模板 `.app` 内所有文件字节和框架符号链接，把固件与设置放在应用旁的隐藏 `.qmk-update` 中。因此 Windows 装包不调用 `codesign`，不修改已签名 `.app` 的资源。客户需保留整个解压文件夹，不能只把 `.app` 单独移走。隐藏固件包仍使用本项目的 SHA-256 完整性校验。

**当前交付包含四系统真实运行模板，制作工具标题显示 v1.0.0。** 最终构建与成品启动验证见 [GitHub Actions](https://github.com/sdk66/qmk_tools/actions/runs/42572980314)，源代码位于 `codex/runtime-templates` 分支，`main` 没有改动。内部运行模板兼容版本保持 1.4.0 / API 4。单元测试中的架构测试样本仅用于异常测试，不会作为真实模板交付。

## 单次与连续烧录

**单次烧录**用于客户升级：双击运行、连接键盘、等待自动完成。只有固件写入和逐页读回校验通过、复位命令成功，且已检测到目标 APP 重新连接并确认 Boot 消失，才显示成功并开始 **5 秒倒计时自动关闭**。校验失败、复位失败或未确认重连时保留窗口和日志，不会启动成功倒计时。

**连续烧录**用于工厂：双击运行后持续等待目标键盘，识别后自动烧录。完成一把后显示成功数量并保持窗口打开，必须拔下已完成的键盘，等待「可连接下一把键盘」提示后再连接下一把。程序同时检查旧 APP、新 APP 和 Boot 全部消失，并过滤短暂丢失的检测结果，防止升级后的同一把被重复烧录。失败也会保留日志，拔下该把后可处理下一把；支持暂停/继续等待。

上面的自动开始行为由「打开后自动开始」控制，默认勾选。取消后，单次包需点击「开始升级」；连续包需点击一次「开始连续烧录」启动工位，后续更换键盘仍连续处理。启动选项会写入包内，客户端会实际等待点击后才发送进 Boot 或烧录命令。

烧录任务运行期间，暂停、重试和普通关闭不会中断写入。无设备或存在多把匹配设备时保持等待，不弹出选择固件的对话框。升级包同时监听正常 APP 和配置的 DFU 标识：匹配 APP 时发送一次 `0x0B`，客户手动进入 DFU 时直接烧录，不会再次发送进入命令。客户无需知道 VID/PID，也无需选择路径。

若自动进入 DFU 失败且尚未开始写入，窗口保持打开，继续等待客户手动进入 DFU，不反复向仍连接的 APP 发送命令。进入 DFU 后的连接、芯片、写入或校验错误仍会停止并保留日志。旧配置的 `allow_boot_recovery` 字段仅为文件兼容保留，已不再作为路径限制。

当前示例固件识别结果：

| 项目 | 结果 |
| --- | --- |
| 产品字符串 | SAMURAI S-751 Keyboard |
| VID / PID | `342D / E594` |
| Usage Page / Usage ID | `FF60 / 0061` |
| 输出报告 | 32 字节，无编号报告 |
| USB bcdDevice | `0009`（发布版本可另行填写） |
| 起始地址 | `0x08000000` |
| 固件有效数据 | 74,068 字节 |

HIDAPI 发送缓冲区为 `00 0B 00 …`，第一个 `00` 是 HIDAPI 要求的 Report ID 槽位；QMK `via_command_kb()` 接收到的数据第一字节是 `0B`。不是发送 ASCII 字符串 `"0x0B"`。

`0x08008000` 和 `2E3C:AF05` 不适用于此示例固件和 WB32 Boot。Boot 的协议为 USB Bulk，不存在 HID Usage Page/Usage ID。

## 客户系统与首次 USB 配置

| 系统 | 构建方案 | 首次准备 |
| --- | --- | --- |
| Windows 7 SP1 / 10 / 11 x64 | Python 3.8.10 + Qt 5.15.2 + PyInstaller 5.13.2 | Boot 设备须安装 WinUSB；Win7 需具备平台更新和对应运行库支持 |
| macOS Intel | Python 3.11 + Qt 6.8.3，Intel 原生构建 | USB/HID 权限；正式发布需厂家签名及公证 |
| macOS Apple Silicon | Python 3.11 + Qt 6.8.3，ARM64 原生构建 | 同上；ARM 和 Intel 分别打包 |
| Linux x64 | 在 Ubuntu 22.04 构建，Qt 6.8.3 | 桌面图形环境及 udev 权限；更老的 glibc 发行版需在其上另行构建 |

Windows **APP Raw HID 使用系统 HID 驱动**。只对 `WB Device in DFU Mode (342D:DFA0)` 使用 WinUSB，不要替换正常键盘接口的 HID 驱动。官方驱动包既放在 `drivers/windows/`，也内置在客户程序中。客户可从「连接帮助」启动厂商安装器，Windows 会请求管理员授权。程序不会静默修改系统驱动。如果客户已经能通过 QMK Toolbox 烧录，通常已有正确的 Boot 驱动。

Linux 的示例规则在 `drivers/70-qmk-wb32.rules`，首次由管理员执行：

```sh
sudo install -m 644 drivers/70-qmk-wb32.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

然后重新插拔键盘。修改 APP VID/PID 后，应相应修改规则。规则同时覆盖 APP USB / hidraw 和 Boot USB，兼容两种 HID 后端。Linux 客户程序的「连接帮助」可导出适配本包实际 APP/Boot 标识的规则。桌面会话通过 `uaccess` 授予当前用户权限；无 systemd/logind 的环境应按发行版配置专用设备组。客户升级程序本身不要求以 root 运行。

Windows 单 EXE / Linux 归档内的可执行文件包含固件，不需要客户选择文件或安装 Python。Windows7 兼容性是构建目标，仍需在准备发布的 Win7 SP1 镜像上实测，包括 USB 权限、WinUSB 和运行库。

macOS 运行模板应在首次构建时完成所需的厂家签名和公证。PyInstaller 默认生成的 ad-hoc 签名不等于 Developer ID 或公证。装包阶段保留 `.app` 内容，正式分发仍需厂家在 Mac 上验证签名、启动和 USB 流程。代码签名覆盖应用资源的原理可参考 [Apple 说明](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/AboutCS/AboutCS.html)。

## 升级行为

- 四项 APP 标识必须全部匹配，只打开选中的 Raw HID 接口。
- 多把匹配键盘、多个 Boot，或 APP 与另一个 Boot 同时存在，均在发送进 Boot 命令前拒绝。
- 必须观察到 APP 消失以及唯一 Boot 出现才继续。Boot 校验 USB 端点、厂商/产品字符串、芯片 ID 和 Q95 的 256 KiB Flash / 36 KiB SRAM。
- HEX 稀疏段保留空洞，不把空洞填成 `FF` 后擦除。先读完所有涉及页面，再逐页保留未覆盖字节、擦除、写入、读回比较；不执行整片擦除。
- 读保护时停止，不自动解除保护或写入芯片信息区域。
- 校验失败保留 Boot；全部校验通过才发复位命令。
- 匹配、进 Boot、芯片检查和页预读保持 0%；页面写入并校验后才开始增加。每次尝试只发送一条退出 DFU 的 `0x83` 命令，重连等待和关闭窗口不重复发送。
- 进 Boot 的 `0x0B` 与写完后的退出是两个不同阶段。完成日志只保留一次成功结果，避免多条确认文字被误认为再次退出。
- 未观察到新固件 HID 返回时显示「写入完成，等待重新连接」，不会显示完整升级成功。
- 进程锁防止同一用户同时启动多个升级任务；升级时阻止正常关闭窗口，支持导出日志。
- 单次和连续模式均尊重「打开后自动开始」设置。取消时先等待点击开始，再允许发送进 Boot 或烧录命令。预览和截图模式始终禁用设备通信；制作工具本身不会发送升级命令。
- 正常 APP 与手动 DFU 入口始终同时启用。仍需使用对应型号的包并只连接一把待升级键盘，因为同款芯片的 ROM Boot 无法区分键盘 PCB 型号。

APP 的四项标识和 Boot 的芯片规格不能证明 PCB 型号。厂家应为每个键盘型号独立分发正确固件包。当前包使用 SHA-256 检查文件损坏，不包含厂家数字签名，也不提供固件来源认证。

## 从源码运行与构建

Windows（**使用 64 位 Python 3.8.10**；不要用 Python 3.12 构建 Win7 包）：

```powershell
python -m pip install -r requirements-windows.txt
python -m unittest discover -s tests -v
python main.py --firmware mk20b_via_v9.hex
python tools/build.py --clean
```

当前工作目录另有 `.tools/python38/tools/python.exe` 隔离环境。可将上面命令中的 `python` 换为该路径。

macOS/Linux（Python 3.11）：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/build.py --clean
```

Ubuntu 22.04 构建前安装系统组件：

```sh
sudo apt-get install libegl1 libopengl0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxkbcommon-x11-0 libhidapi-hidraw0 libusb-1.0-0
```

`.github/workflows/build.yml` 包含 Windows x64、macOS Intel/ARM64、Linux x64 四个原生构建任务。每个任务导出运行模板并制作示例客户包，再验证冻结程序启动；最后汇总成 `QMK-All-System-Templates.zip`，供 Windows 工具一次性导入。下载 GitHub artifact 后，如外面还有一层 ZIP，先解压取得这个模板集合文件。推送构建分支会自动重新构建，工作流合入默认分支后也可手动触发。

每次 `tools/build.py` 构建都会在 `release/` 导出对应 `.qmk-runtime.zip`。模板需为 **1.5.0 / Runtime API 5**，以支持 APP/手动 DFU 双路径、切换竞态处理与自动入口失败后的持续等待。制作工具标题仍显示 v1.0.0。导入后的目录位于制作工具旁：

```text
templates/
  windows-x64.qmk-runtime.zip
  linux-x64.qmk-runtime.zip
  macos-x64.qmk-runtime.zip
  macos-arm64.qmk-runtime.zip
```

Windows/Linux 从模板复制可执行文件并嵌入包数据；Mac 从模板复制完整应用与外部固件包，三个系统的装包代码均可在 Windows 运行。运行模板的首次构建仍需要对应平台，因为 [PyInstaller 本身不是跨系统编译器](https://github.com/pyinstaller/pyinstaller#pyinstaller-overview)。Windows 代码签名应在生成最终客户 EXE 后进行；重打包会移除模板旧签名。

命令行制作、检查和安全预览：

```powershell
python tools/make_package.py --firmware mk20b_via_v9.hex --output examples/SAMURAI-S751-v0.0.9.qmk
python tools/make_package.py --firmware mk20b_via_v9.hex --template dist/QMK-Firmware-Studio.exe --output SAMURAI-S751-v0.0.9.exe
python tools/make_package.py --firmware mk20b_via_v9.hex --mode continuous --template dist/QMK-Firmware-Studio.exe --output SAMURAI-S751-v0.0.9-factory.exe
python tools/make_package.py --firmware mk20b_via_v9.hex --manual-start --template dist/QMK-Firmware-Studio.exe --output SAMURAI-S751-manual.exe
python tools/make_package.py --firmware mk20b_via_v9.hex --runtime templates/macos-arm64.qmk-runtime.zip --output SAMURAI-S751-mac.zip
python tools/make_package.py --firmware mk20b_via_v9.hex --background "#11151C" --output examples/dark.qmk
python main.py --inspect examples/SAMURAI-S751-v0.0.9.qmk
python main.py --package examples/SAMURAI-S751-v0.0.9.qmk --preview
python main.py --firmware mk20b_via_v9.hex --screenshot maker-preview.png
```

## 协议来源与第三方许可

WB32 Bulk 实现移植自 [WestberryTech/wb32-dfu-updater](https://github.com/WestberryTech/wb32-dfu-updater)，保留 Apache-2.0 归属与许可；原始厂商代码放在 `vendor/` 供核对。QMK 的 WB32 刷写流程可参见 [QMK 官方说明](https://github.com/qmk/qmk_firmware/blob/master/docs/flashing.md#wb32-dfu)。本项目没有内嵌其他品牌的 IAP 协议，也不调用 QMK Toolbox 窗口自动化。

第三方依赖说明见 `THIRD_PARTY_NOTICES.md`。构建时会将依赖自身的许可文件复制进程序和 `release/<平台>/licenses/`。图标 `icon.png` 和示例固件由用户提供，其权利归原作者。
