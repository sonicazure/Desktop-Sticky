# -*- coding: utf-8 -*-
"""通用小工具：高 DPI 感知、可点击标记、颜色明暗处理。"""


def enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def clickable(widget):
    widget._is_clickable = True
    widget.config(cursor="hand2")
    return widget


def shade_color(hex_color, factor):
    """把 #RRGGBB 按比例调亮（factor>1）或调暗（factor<1）。

    用于开关轨道 / 按钮的立体描边（高光与阴影），不依赖 tk 窗口实例。
    """
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    channels = [min(255, max(0, int(round(c * factor)))) for c in channels]
    return "#%02x%02x%02x" % tuple(channels)


def ink_dy(font_size):
    """文字油墨视觉中线相对其行框几何中线的下偏量（像素）。

    Tk 按行框居中排布文字，但 CJK 字体的油墨实际分布偏下，
    导致画布绘制的圆点 / 开关看起来比文字中线高 1~2px。
    绘制类元素（勾选圆点、Switch）按此值下移即可与文字视觉对齐。
    """
    return max(1, int(round(font_size * 0.15)))
