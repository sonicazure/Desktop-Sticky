# -*- coding: utf-8 -*-
"""
To-Do List 桌面小组件 v7（模块化重构版）
========================================
- 无边框窗口：标题栏拖动移动，右 / 下 / 右下角贴边缩放（拖拽时每帧同步布局，不闪不空）
- 高 DPI 感知渲染；标题锁定 Times New Roman 加粗，不随设置变化
- 透明度 0–100% 滑杆（有序抖动点阵）：窗口底板与【待办卡片底色】一起淡出，
  文字、勾选框、按钮永远实心清晰 —— 与敬业签 / 小黄条的透明便签一致
- 待办卡片为画布绘制：底色可透明、文字实心、悬停浮现删除键
- 双主题：亮色（白底黑字）/ 暗色（黑底白字）
- 设置为独立静态弹窗：禁缩放、无滚动
- 双击文字行内编辑；删除 / 清除可撤销；双击标题栏折叠
- 数据原子写入 + .bak 备份 + 保存失败提示；开机自启路径自愈

运行：python main.py（或双击「启动待办清单.bat」）
仅依赖 Python 自带 tkinter，零第三方库。

代码结构：
    desktop_todo/constants.py   常量（主题、字号档位、色键、抖动矩阵）
    desktop_todo/storage.py     数据目录定位与 JSON 原子读写
    desktop_todo/autostart.py   开机自启动（注册表）
    desktop_todo/utils.py       DPI 感知 / 可点击标记 / 颜色明暗
    desktop_todo/widgets.py     自定义控件（矩形滑块开关 Switch）
    desktop_todo/todo_item.py   单条待办卡片
    desktop_todo/dialogs.py     弹窗（新建待办 / 设置 / 字体选择）
    desktop_todo/app.py         主程序 TodoApp
    main.py                     程序入口
"""
from desktop_todo.app import TodoApp

if __name__ == "__main__":
    TodoApp().run()
