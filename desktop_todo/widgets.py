# -*- coding: utf-8 -*-
"""自定义控件：矩形滑块开关（Switch）与扁平滑动条（Slider）。

两者共用一套设计语言：立体描边轨道 + 纯平矩形钮。
"""
import tkinter as tk

from .utils import clickable, shade_color


class Switch(tk.Canvas):
    """矩形滑块开关。

    视觉设计：
    - 轨道为纯矩形（无圆弧，边缘零锯齿），周遭带 1px 左上高光 +
      1px 右下阴影的凸起立体描边（仿设置页顶部透明度滑动条的
      raised 轮廓效果）；
    - 选择钮为纯平纯白矩形（无描边），与立体轨道形成材质对比。
    """

    W, H = 50, 28

    def __init__(self, master, on=False, command=None,
                 accent="#E8A93D", off="#C4CAD2", bg="#FFFFFF"):
        super().__init__(master, width=self.W, height=self.H, bg=bg,
                         highlightthickness=0, bd=0)
        clickable(self)
        self.on = on
        self.command = command
        self.accent = accent
        self.off = off
        self._kx = float(self.W - self.H) if on else 0.0
        self._anim = None
        self.bind("<Button-1>", self._click)
        self.bind("<Destroy>", lambda e: self._cancel_anim())
        self._draw()

    def _cancel_anim(self):
        if self._anim:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None

    def set_on(self, on, fire=False):
        if on == self.on:
            return
        self.on = on
        self._animate_to(float(self.W - self.H) if on else 0.0)
        if fire and self.command:
            self.command(on)

    def _click(self, _e):
        self.set_on(not self.on, fire=True)

    def _animate_to(self, target):
        self._cancel_anim()
        start, steps = self._kx, 6

        def step(i):
            if not self.winfo_exists():
                return
            self._kx = start + (target - start) * i / steps
            self._draw()
            if i < steps:
                self._anim = self.after(14, lambda: step(i + 1))
            else:
                self._anim = None
        step(1)

    def _draw(self):
        self.delete("all")
        w, h = self.W, self.H
        track = self.accent if self.on else self.off
        # 画布底色铺满，消除边缘杂点
        self.create_rectangle(0, 0, w, h, fill=self.cget("bg"), outline="")
        # 纯矩形轨道（无圆弧 = 无抗锯齿锯齿）+ 立体凸起描边
        # （参照透明度滑杆的 raised 轮廓）：
        # 右下 1px 深阴影 + 左上 1px 亮高光，轨道本体内缩 1px 使其露出
        self.create_rectangle(1, 1, w, h,
                              fill=shade_color(track, 0.55), outline="")
        self.create_rectangle(0, 0, w - 1, h - 1,
                              fill=shade_color(track, 1.35), outline="")
        self.create_rectangle(1, 1, w - 1, h - 1, fill=track, outline="")
        # 矩形选择钮：纯平纯白（无描边无渐变），与轨道的立体轮廓形成对比
        kx = self._kx
        self.create_rectangle(kx + 4, 4, kx + h - 4, h - 4,
                              fill="#FFFFFF", outline="")


class Slider(tk.Canvas):
    """扁平化滑动条（透明度等数值调节）。

    视觉设计与 Switch 统一：
    - 轨道为细长矩形，已填充段用 accent 色、未填充段用灰色，
      整轨带 1px 左上高光 + 1px 右下阴影的立体描边；
    - 滑钮为纯平矩形（带 1px 平面灰描边，在亮色面板上也有辨识度）；
    - dy：图形整体下偏量，用于对齐同行文字的油墨中线。

    交互：点击跳转 + 拖拽；command(v) 拖动中持续回调，
    release(v) 松手时回调一次。
    """

    H = 28
    TRACK_H = 8
    KNOB_W, KNOB_H = 12, 20

    def __init__(self, master, from_=0, to=100, value=0, length=190,
                 command=None, release=None,
                 accent="#E8A93D", trough="#9C9CA5", bg="#FFFFFF", dy=0):
        super().__init__(master, width=length, height=self.H, bg=bg,
                         highlightthickness=0, bd=0)
        clickable(self)
        self.from_, self.to = from_, to
        self.command = command
        self.release = release
        self.accent = accent
        self.trough = trough
        self.length = length
        self.dy = dy
        self._val = int(value)
        self.bind("<Button-1>", self._jump)
        self.bind("<B1-Motion>", self._jump)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def get(self):
        return self._val

    def set(self, v):
        self._val = int(v)
        self._draw()

    def _pad(self):
        return self.KNOB_W / 2 + 2

    def _jump(self, e):
        pad = self._pad()
        frac = (e.x - pad) / max(1, self.length - 2 * pad)
        frac = min(max(frac, 0.0), 1.0)
        val = int(round(self.from_ + frac * (self.to - self.from_)))
        if val != self._val:
            self._val = val
            self._draw()
        if self.command:
            self.command(self._val)

    def _on_release(self, _e):
        if self.release:
            self.release(self._val)

    def _draw(self):
        self.delete("all")
        w, h = self.length, self.H
        # 画布底色铺满，消除边缘杂点
        self.create_rectangle(0, 0, w, h, fill=self.cget("bg"), outline="")
        cy = h / 2 + self.dy
        pad = self._pad()
        x0, x1 = pad, w - pad
        t = self.TRACK_H / 2
        frac = (self._val - self.from_) / max(1, self.to - self.from_)
        kx = x0 + (x1 - x0) * frac
        # 整轨立体描边：右下 1px 阴影 + 左上 1px 高光，本体内缩 1px
        self.create_rectangle(x0 + 1, cy - t + 1, x1 + 1, cy + t + 1,
                              fill=shade_color(self.trough, 0.55), outline="")
        self.create_rectangle(x0 - 1, cy - t - 1, x1, cy + t,
                              fill=shade_color(self.trough, 1.5), outline="")
        # 未填充段（灰）+ 已填充段（accent），均内缩 1px 露出描边
        self.create_rectangle(x0, cy - t + 1, x1, cy + t - 1,
                              fill=self.trough, outline="")
        if kx > x0 + 1:
            self.create_rectangle(x0, cy - t + 1, kx, cy + t - 1,
                                  fill=self.accent, outline="")
        # 纯平矩形滑钮：白底 + 1px 平面灰描边（亮色面板下也可辨）
        self.create_rectangle(kx - self.KNOB_W / 2, cy - self.KNOB_H / 2,
                              kx + self.KNOB_W / 2, cy + self.KNOB_H / 2,
                              fill="#FFFFFF",
                              outline=shade_color("#FFFFFF", 0.72),
                              width=1)
