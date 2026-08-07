# 桌面待办清单（Desktop To-Do Widget）

一个轻量的 Windows 桌面待办小组件：**纯 Python 标准库（tkinter）实现，零第三方依赖**，不需要安装任何 pip 包即可运行。

## 功能特性

- **无边框透明桌面组件**：色键抠像（chroma-key）实现任意透明度，背景用有序抖动点阵模拟分级半透明，无廉价感
- **整卡交互**：单击卡片 = 完成/恢复（带沉底/回升滑动动画），双击 = 就地编辑，长按 = 拖拽排序（替身窗口拖拽，流畅不卡顿）
- **编辑模式模态化**：编辑中点击其他任意位置只会保存退出，不会误触发其他交互
- **槽位自适应高度**：默认 3 个槽位，第 4 条起每条 +1 槽，上限 10 槽，可拖拽下边缘按槽位吸附调整
- **亮/暗双主题**：思源宋体分组标题、可换字体字号、透明度滑杆
- **撤销删除**：删除后底部弹出撤销条，可反悔
- **数据持久化**：待办与设置保存在 `%APPDATA%`，重启、移动 exe 均不丢数据
- **开机自启**：通过 Windows 注册表 Run 键实现，路径变更时下次启动自动自愈

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `main.py` | 程序入口 |
| `desktop_todo/` | 主程序包（模块化结构，见下） |
| `启动待办清单.bat` | 双击运行（等价于 `pythonw main.py`） |

`desktop_todo/` 包结构：

| 模块 | 职责 |
| --- | --- |
| `constants.py` | 常量：主题配色、字号档位、色键、抖动矩阵 |
| `storage.py` | 数据目录定位与 JSON 原子读写（.bak 备份） |
| `autostart.py` | 开机自启动（注册表 Run 键） |
| `utils.py` | DPI 感知、可点击标记、颜色明暗计算 |
| `widgets.py` | 自定义控件（矩形滑块开关 Switch） |
| `todo_item.py` | 单条待办卡片 |
| `dialogs.py` | 弹窗：新建待办 / 设置 / 字体选择 |
| `app.py` | 主程序 TodoApp（窗口、布局、排序动画、贴边缩放） |

## 运行

需要 Windows + Python 3（安装时勾选 "Add python.exe to PATH"）：

```
pythonw main.py
```

或直接双击 `启动待办清单.bat`。

## 打包为 exe

```
python -m PyInstaller --onefile --noconsole --name "Desktop Sticky" main.py
```

## 数据位置

待办数据与配置存储在 `%APPDATA%\DesktopTodoWidget\` 下，与程序位置无关，exe 可随意移动。
