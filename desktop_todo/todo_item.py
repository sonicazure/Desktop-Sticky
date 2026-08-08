# -*- coding: utf-8 -*-
"""单条待办卡片：画布直绘（底色可透明、文字实心、悬停浮现删除键）。"""
import tkinter as tk

from .constants import CARD_W, KEY
from .utils import clickable, ink_dy


class TodoItem:
    PAD = 12          # 卡片上下内边距
    LEFT = 14         # 勾选框左边距
    DEL_RESERVE = 30  # 删除键预留宽度（兜底值，实际按字形实测）
    EDIT_GAP = 18     # 行内编辑框与删除键之间的额外净空

    def __init__(self, app, todo):
        self.app = app
        self.todo = todo
        self._click_job = None
        self._lp_job = None
        self._pressed = False
        self._edit_entry = None
        self._edit_win = None
        self._hovered = False
        self._flash_jobs = []
        self.height = 48
        th = app.theme

        weight = "bold" if app.font_bold else "normal"
        self.font_normal = app.font(app.font_family, app.font_size, weight)
        self.font_done = app.font(app.font_family, app.font_size, weight,
                                  overstrike=True)
        self.check_size = max(16, int(round((app.font_size + 10) * 0.75)))
        self._ink_dy = ink_dy(app.font_size)  # 油墨中线相对几何中线的下偏量
        self.text_left = self.LEFT + self.check_size + 12
        self._stip_light = app._stipple_for(16)
        self._stip_dense = app._stipple_for(72)
        self._check_hover = False
        self._chk_ring = None
        self._glyph_w = None  # ✕ 字形宽度缓存（实例生命周期内字体不变）

        # 画布底色必须是色键：卡片矩形的透明点阵（透明度滑杆）要透过
        # 它看到桌面。嵌入窗口为 CARD_W 固定超宽、右缘由父画布裁剪，
        # 矩形未覆盖的右侧细条由 strip 补条按列表背景同款填充+点阵
        # 补足——否则那里会露出一条透出桌面的虚线竖缝
        c = tk.Canvas(app.canvas, bg=KEY, highlightthickness=0, bd=0,
                      height=self.height)
        clickable(c)
        self.widget = c
        self.strip = c.create_rectangle(0, 0, 0, 0, width=0)
        self.rect = c.create_rectangle(0, 0, 10, 10, width=1)
        # 勾选圆圈直接画在卡片画布上，不用子控件——任何透明度下都无痕
        # （点击由整卡 press/release 统一处理，圆圈仅保留悬停变色）
        c.tag_bind("chk", "<Enter>", lambda e: self._check_hover_set(True))
        c.tag_bind("chk", "<Leave>", lambda e: self._check_hover_set(False))
        self.text_item = c.create_text(self.text_left, 24, anchor="w",
                                       text=todo["text"],
                                       font=self.font_normal, fill=th["fg"],
                                       width=180)
        self.del_item = c.create_text(0, 24, anchor="e", text="✕",
                                      fill=th["sub"], state="hidden",
                                      font=(app.font_family, app.font_size + 2))
        c.tag_bind(self.del_item, "<Button-1>", self._del_click)
        c.tag_bind(self.del_item, "<Enter>",
                   lambda e: c.itemconfig(self.del_item, fill="#E5534B"))
        c.tag_bind(self.del_item, "<Leave>",
                   lambda e: c.itemconfig(self.del_item, fill=th["sub"]))
        # 整卡交互：单击=划掉/恢复，双击=编辑，长按拖动=排序
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._dblclick)
        c.bind("<Enter>", self._hover_on)
        c.bind("<Leave>", self._hover_off)
        c.bind("<Destroy>", self._on_destroy_item)
        self._refresh_style()
        self.apply_surface()

    # ---------- 表面（底色随透明度点阵淡出，文字不变） ----------
    def apply_surface(self, flash_color=None):
        th = self.app.theme
        pct = self.app.chrome_opacity
        stip = self.app._stipple_for(pct)
        if flash_color:
            base = flash_color
        else:
            base = th["hover"] if self._hovered else th["item"]
        fill = KEY if pct < 4 else base
        self.widget.itemconfig(
            self.rect, fill=fill, stipple=stip,
            outline=(th["border"] if pct >= 96 else ""))
        # 右侧补条与列表背景完全同款（app.py 中 list_bg 的逻辑）：
        # 透明度变化时补条与背景同步淡出，观感无缝
        self.widget.itemconfig(
            self.strip, fill=(KEY if pct < 4 else th["bg"]), stipple=stip)

    # ---------- 尺寸 ----------
    def _del_glyph_w(self):
        """删除键 ✕ 的实际字形宽度（高 DPI / 大字号下远超字号的兜底估算）。
        隐藏状态下 bbox 不可用，先临时置为可见同步测量再恢复——
        全程在同一事件处理内完成，不会触发中间帧重绘。
        结果缓存：拖拽中每帧都会用到，而字体在实例生命周期内不变。"""
        if self._glyph_w is not None:
            return self._glyph_w
        c = self.widget
        hidden = c.itemcget(self.del_item, "state") == "hidden"
        if hidden:
            c.itemconfig(self.del_item, state="normal")
        bbox = c.bbox(self.del_item)
        if hidden:
            c.itemconfig(self.del_item, state="hidden")
        if bbox:
            self._glyph_w = bbox[2] - bbox[0]
        else:
            self._glyph_w = self.DEL_RESERVE - 14  # 兜底：退回字号估算
        return self._glyph_w

    def _text_reserve(self):
        """文字 / 编辑框右侧应让出的总宽度：✕ 右缘边距 + 字形宽 + 间隔。"""
        return 16 + self._del_glyph_w() + 8

    def set_frame_width(self, cw):
        """宽度过渡（拖拽中逐帧调用）：边框、右侧补条、删除键即时跟随，
        文字换行也实时跟随——否则缩窄时文字会溢出卡片右缘外，直到
        80ms 防抖 restack 才收回，表现为"不跟光标、乱跳"（旧的逐帧
        HWND 缩放靠窗口裁剪遮住了这种溢出）。高度重测仍留给防抖
        restack，避免逐帧量高开销。"""
        self.widget.coords(self.rect, 0, 0, cw, self.height)
        self.widget.coords(self.strip, cw, 0, CARD_W, self.height)
        self.widget.coords(self.del_item, cw - 16, self.height / 2)
        self.set_width(cw)

    def set_width(self, cw):
        self.width = cw
        self.widget.itemconfig(self.text_item,
                               width=cw - self.text_left
                               - self._text_reserve())

    def measure(self):
        bbox = self.widget.bbox(self.text_item)
        text_h = (bbox[3] - bbox[1]) if bbox else 20
        return max(text_h, self.check_size) + self.PAD * 2

    def layout(self, cw, h):
        self.height = h
        mid = h / 2
        self.widget.coords(self.rect, 0, 0, cw, h)
        self.widget.coords(self.strip, cw, 0, CARD_W, h)
        self.widget.coords(self.text_item, self.text_left, mid)
        self.widget.coords(self.del_item, cw - 16, mid)
        self.widget.config(height=h)
        self._draw_check()

    # ---------- 勾选圆圈（画布直绘，磨砂玻璃质感） ----------
    def _draw_check(self):
        c = self.widget
        c.delete("chk")
        th = self.app.theme
        s = self.check_size
        x0 = self.LEFT
        # 对齐文字油墨的视觉中线（bbox 中心），而不是卡片几何中线：
        # 字体的 ascent/descent 不对称，几何中线会比文字视觉中线低 1~2px
        bbox = c.bbox(self.text_item)
        cy = (bbox[1] + bbox[3]) / 2 if bbox else self.height / 2
        # 油墨视觉中线比行框几何中线低 ink_dy，圆点随之下移对齐
        y0 = cy + self._ink_dy - s / 2
        ring_p = 2.2
        fill_p = ring_p + 2.4
        if self.todo.get("done", False):
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["sub"],
                          stipple=self._stip_dense, outline="", tags="chk")
            self._chk_ring = c.create_oval(
                x0 + ring_p, y0 + ring_p, x0 + s - ring_p, y0 + s - ring_p,
                outline=th["sub"], width=2.2, tags="chk")
        else:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["accent"],
                          stipple=self._stip_light, outline="", tags="chk")
            self._chk_ring = c.create_oval(
                x0 + ring_p, y0 + ring_p, x0 + s - ring_p, y0 + s - ring_p,
                outline=th["accent"], width=2.0, tags="chk")
        # 圆圈置顶于卡片底色之上
        c.tag_raise("chk", self.rect)

    def _del_click(self, _e):
        self.app.delete_todo(self.todo["id"])
        return "break"  # 阻断卡片单击勾选

    # ---------- 整卡交互：单击划掉 / 双击编辑 / 长按拖动排序 ----------
    def _press(self, e):
        if self._edit_entry:
            return
        editing = self.app._editing_item
        if editing and editing is not self:
            # 其他条目正在编辑：点击任何位置只保存退出，不触发交互。
            # 注意：保存会重建全部卡片，本次松开事件会落到原地那张
            # 新建卡片上——新卡片的 _pressed 为 False，天然拦截
            editing._commit_edit()
            return
        self._pressed = True
        self._press_y_root = e.y_root
        # 长按 450ms 进入拖动排序
        self._lp_job = self.app.root.after(450, self._begin_reorder)

    def _motion(self, e):
        if self.app._reorder:
            self.app._reorder_motion(e.y_root)  # 应用级状态接力

    def _release(self, _e):
        if self.app._reorder:
            self.app._commit_reorder()  # 松开可能落在任意卡片上
            return
        if not self._pressed:
            return  # 无按下不处理：卡片重建后落到新卡片上的游离松开事件
        self._pressed = False
        if self._lp_job:
            self.app.root.after_cancel(self._lp_job)
            self._lp_job = None
        if self._edit_entry:
            return
        # 单击：延迟判定，双击会取消
        if self._click_job:
            self.app.root.after_cancel(self._click_job)
        self._click_job = self.app.root.after(250, self._fire_toggle)

    def _begin_reorder(self):
        self._lp_job = None
        if self._edit_entry:
            return
        if self._click_job:
            self.app.root.after_cancel(self._click_job)
            self._click_job = None
        self.app._begin_reorder(self)

    def _dblclick(self, _e):
        editing = self.app._editing_item
        if editing and editing is not self:
            editing._commit_edit()
            return "break"
        if self._lp_job:
            self.app.root.after_cancel(self._lp_job)
            self._lp_job = None
        if self._click_job:
            self.app.root.after_cancel(self._click_job)
            self._click_job = None
        self._start_edit()
        return "break"

    def _fire_toggle(self):
        self._click_job = None
        try:
            if not self.widget.winfo_exists():
                return
        except Exception:
            return
        if not self._edit_entry:
            self._toggled(not self.todo.get("done", False))

    def _check_hover_set(self, on):
        # 去重守卫：重绘后新元素出现在指针下方会再次触发 <Enter>，
        # 若不加守卫会形成“悬停->重绘->再悬停”的无限事件风暴（卡死根因）
        if on == self._check_hover:
            return
        self._check_hover = on
        if self.todo.get("done", False):
            return  # 勾选态圆环颜色不随悬停变化
        try:
            # 只改圆环颜色，不删建元素，避免再次触发悬停事件
            self.widget.itemconfig(
                self._chk_ring,
                outline=self.app.theme["accent"])
        except Exception:
            pass

    # ---------- 行内编辑 ----------
    def _start_edit(self):
        if self._edit_entry:
            return
        self.app._editing_item = self  # 编辑期间，外部点击只保存退出
        th = self.app.theme
        self.widget.itemconfig(self.text_item, state="hidden")
        entry = tk.Entry(self.widget, font=self.font_normal, relief="flat",
                         bd=0, highlightthickness=0, bg=th["hover"],
                         fg=th["fg"], insertbackground=th["fg"])
        entry.insert(0, self.todo["text"])
        entry.select_range(0, "end")
        cw = getattr(self, "width", 240)
        # 编辑框右缘 = ✕ 左缘再让 EDIT_GAP：按字形实测宽度动态缩短，
        # 高 DPI / 大字号下 ✕ 很宽，固定预留会被挡住
        self._edit_win = self.widget.create_window(
            self.text_left, self.height / 2, window=entry, anchor="w",
            width=max(60, cw - self.text_left - self._text_reserve()
                      - self.EDIT_GAP))
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._commit_edit())
        entry.bind("<Escape>", lambda e: self._cancel_edit())
        entry.bind("<FocusOut>", lambda e: self._commit_edit())
        self._edit_entry = entry

    def _commit_edit(self):
        if not self._edit_entry:
            return
        text = self._edit_entry.get().rstrip()
        self._edit_entry = None
        self.app._editing_item = None
        if text and text != self.todo["text"]:
            self.app.update_todo_text(self.todo["id"], text)
        else:
            self.app.render_items()

    def _cancel_edit(self):
        self._edit_entry = None
        self.app._editing_item = None
        self.app.render_items()

    # ---------- 悬停 ----------
    def _hover_on(self, _e):
        self._hovered = True
        self.apply_surface()
        self.widget.itemconfig(self.del_item, state="normal")

    def _hover_off(self, _e):
        x, y = self.widget.winfo_pointerxy()
        w = self.widget.winfo_containing(x, y)
        if w and (w is self.widget or str(w).startswith(str(self.widget))):
            return
        self._hovered = False
        self.apply_surface()
        self.widget.itemconfig(self.del_item, state="hidden")

    # ---------- 动效 ----------
    def flash(self):
        th = self.app.theme
        base = th["item"]
        start = self.app.lerp(base, th["accent"], 0.28)
        steps = 6
        for i in range(steps + 1):
            color = None if i == steps else self.app.lerp(start, base, i / steps)
            job = self.app.root.after(
                i * 70, lambda c=color: self._safe_flash(c))
            self._flash_jobs.append(job)

    def _safe_flash(self, color):
        try:
            if self.widget.winfo_exists():
                self.apply_surface(flash_color=color)
        except Exception:
            pass

    def _on_destroy_item(self, e):
        if e.widget is self.widget:
            for attr in ("_click_job", "_lp_job"):
                job = getattr(self, attr, None)
                if job:
                    try:
                        self.app.root.after_cancel(job)
                    except Exception:
                        pass
                    setattr(self, attr, None)
            for job in self._flash_jobs:
                try:
                    self.app.root.after_cancel(job)
                except Exception:
                    pass
            self._flash_jobs = []

    # ---------- 勾选 ----------
    def _toggled(self, done):
        self.app.toggle_todo(self.todo["id"], done)
        try:
            # 勾选动画的置顶会重建本卡片，旧控件已销毁则无需再刷样式
            if self.widget.winfo_exists():
                self._refresh_style()
                self._draw_check()
        except Exception:
            pass

    def _refresh_style(self):
        th = self.app.theme
        if self.todo.get("done", False):
            self.widget.itemconfig(self.text_item, font=self.font_done,
                                   fill=th["sub"])
        else:
            self.widget.itemconfig(self.text_item, font=self.font_normal,
                                   fill=th["fg"])
