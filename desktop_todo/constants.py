# -*- coding: utf-8 -*-
"""全局常量：窗口尺寸、色键、主题配色、字号档位与有序抖动矩阵。"""
import sys

APP_NAME = "DesktopTodoWidget"
MIN_W, MIN_H = 280, 240
HEADER_H = 64
EDGE = 12            # 边缘缩放感应宽度（像素）
CARD_W = 3200        # 卡片嵌入窗口的固定超宽宽度：超出部分由列表画布裁剪，
                     # 水平缩放时卡片原生窗口零尺寸变更（避免逐帧透明擦除频闪）
KEY = "#808080"     # 色键：该颜色像素完全透明（文字与图标不使用此色）
TITLE_FONT = ("Times New Roman", 15, "bold")   # 标题锁定字体，不随设置更改

SIZE_CHOICES = [9, 10, 11, 12, 14]

THEMES = {
    "亮色": dict(bg="#FAF9F6", header="#FFFFFF", header_fg="#1A1A1A",
                 item="#FFFFFF", hover="#F3F1EA", fg="#1A1A1A",
                 sub="#6E6A5E", accent="#E8A93D", border="#E8E5DB",
                 panel="#FFFFFF"),
    "暗色": dict(bg="#1B1B1E", header="#232326", header_fg="#F4F4F5",
                 item="#26262A", hover="#333338", fg="#F4F4F5",
                 sub="#9C9CA5", accent="#F0B44C", border="#3B3B41",
                 panel="#232326"),
}

# 8x8 有序抖动（Bayer）矩阵，用于生成任意密度的透明点阵
_BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]

# 光标名称跨平台兼容
_IS_WIN = sys.platform.startswith("win")
CURSOR_WE = "size_we" if _IS_WIN else "sb_h_double_arrow"
CURSOR_NS = "size_ns" if _IS_WIN else "sb_v_double_arrow"
CURSOR_NWSE = "size_nw_se" if _IS_WIN else "bottom_right_corner"
