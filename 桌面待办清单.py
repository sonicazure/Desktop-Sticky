# -*- coding: utf-8 -*-
"""
To-Do List 桌面小组件 v7
========================
- 无边框窗口：标题栏拖动移动，右 / 下 / 右下角贴边缩放（拖拽时每帧同步布局，不闪不空）
- 高 DPI 感知渲染；标题锁定 Times New Roman 加粗，不随设置变化
- 透明度 0–100% 滑杆（有序抖动点阵）：窗口底板与【待办卡片底色】一起淡出，
  文字、勾选框、按钮永远实心清晰 —— 与敬业签 / 小黄条的透明便签一致
- 待办卡片为画布绘制：底色可透明、文字实心、悬停浮现删除键
- 双主题：亮色（白底黑字）/ 暗色（黑底白字）
- 设置为独立静态弹窗：禁缩放、无滚动
- 双击文字行内编辑；删除 / 清除可撤销；双击标题栏折叠
- 数据原子写入 + .bak 备份 + 保存失败提示；开机自启路径自愈

运行：python 桌面待办清单.py（或双击「启动待办清单.bat」）
打包 exe：运行「打包exe.bat」（需先 pip install pyinstaller）
仅依赖 Python 自带 tkinter，零第三方库。
"""

import json

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont

APP_NAME = "DesktopTodoWidget"
MIN_W, MIN_H = 280, 240
HEADER_H = 64
EDGE = 6            # 边缘缩放感应宽度（像素）
KEY = "#808080"     # 色键：该颜色像素完全透明（文字与图标不使用此色）
TITLE_FONT = ("Times New Roman", 15, "bold")   # 标题锁定字体，不随设置更改

SIZE_CHOICES = [10, 11, 12, 14, 16, 18]

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


# ---------------- 高 DPI 感知 ----------------
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


# ---------------- 数据目录与读写 ----------------
def _data_dir():
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), APP_NAME),
        os.path.join(os.path.expanduser("~"), "." + APP_NAME),
        os.path.dirname(os.path.abspath(__file__)),
    ]
    for d in candidates:
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return d
        except Exception:
            continue
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = _data_dir()
DATA_FILE = os.path.join(DATA_DIR, "todos.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data, backup=True):
    """原子写入：先写临时文件再替换；替换前把旧版留作 .bak 备份。"""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if backup and os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
            except Exception:
                pass
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ---------------- 开机自启动（注册表） ----------------
def set_autostart(enabled: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        if enabled:
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                w = exe[:-10] + "pythonw.exe"
                if os.path.exists(w):
                    exe = w
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                              f'"{exe}" "{os.path.abspath(__file__)}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def get_autostart_value():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ,
        )
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


def get_autostart() -> bool:
    return get_autostart_value() is not None


# 光标名称跨平台兼容
_IS_WIN = sys.platform.startswith("win")
CURSOR_WE = "size_we" if _IS_WIN else "sb_h_double_arrow"
CURSOR_NS = "size_ns" if _IS_WIN else "sb_v_double_arrow"
CURSOR_NWSE = "size_nw_se" if _IS_WIN else "bottom_right_corner"


def clickable(widget):
    widget._is_clickable = True
    widget.config(cursor="hand2")
    return widget


# ---------------- 圆形勾选框 ----------------
# ---------------- iOS 风格开关 ----------------
class Switch(tk.Canvas):
    W, H = 46, 27

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
        start, steps = self._kx, 5

        def step(i):
            if not self.winfo_exists():
                return
            self._kx = start + (target - start) * i / steps
            self._draw()
            if i < steps:
                self._anim = self.after(18, lambda: step(i + 1))
            else:
                self._anim = None
        step(1)

    def _draw(self):
        self.delete("all")
        w, h = self.W, self.H
        track = self.accent if self.on else self.off
        self.create_oval(0, 0, h, h, fill=track, outline="")
        self.create_oval(w - h, 0, w, h, fill=track, outline="")
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=track, outline="")
        kx = self._kx
        self.create_oval(kx + 3, 3, kx + h - 3, h - 3,
                         fill="#FFFFFF", outline="#D8DCE2")


# ---------------- 单条待办（画布卡片：底色可透明，文字实心） ----------------
class TodoItem:
    PAD = 12          # 卡片上下内边距
    LEFT = 14         # 勾选框左边距
    DEL_RESERVE = 30  # 删除键预留宽度

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
        self.check_size = max(26, app.font_size + 14)
        self.text_left = self.LEFT + self.check_size + 12
        self._stip_light = app._stipple_for(16)
        self._stip_dense = app._stipple_for(72)
        self._check_hover = False
        self._chk_ring = None

        c = tk.Canvas(app.canvas, bg=KEY, highlightthickness=0, bd=0,
                      height=self.height)
        clickable(c)
        self.widget = c
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

    # ---------- 尺寸 ----------
    def set_frame_width(self, cw):
        """廉价宽度过渡：只动边框与删除键位置，文字暂不重排（拖拽中）。"""
        self.widget.coords(self.rect, 0, 0, cw, self.height)
        self.widget.coords(self.del_item, cw - 16, self.height / 2)

    def set_width(self, cw):
        self.width = cw
        self.widget.itemconfig(self.text_item,
                               width=cw - self.text_left - self.DEL_RESERVE)

    def measure(self):
        bbox = self.widget.bbox(self.text_item)
        text_h = (bbox[3] - bbox[1]) if bbox else 20
        return max(text_h, self.check_size) + self.PAD * 2

    def layout(self, cw, h):
        self.height = h
        mid = h / 2
        self.widget.coords(self.rect, 0, 0, cw, h)
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
        y0 = (self.height - s) / 2
        ring_p = 2.2
        fill_p = ring_p + 2.4
        if self.todo.get("done", False):
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["accent"],
                          stipple=self._stip_dense, outline="", tags="chk")
            self._chk_ring = c.create_oval(
                x0 + ring_p, y0 + ring_p, x0 + s - ring_p, y0 + s - ring_p,
                outline=th["accent"], width=2.2, tags="chk")
            k = s / 26.0
            pts = [x0 + 7.2 * k, y0 + 13.2 * k, x0 + 11.2 * k, y0 + 17.0 * k,
                   x0 + 18.8 * k, y0 + 7.8 * k]
            c.create_line(*pts, fill="#FFFFFF", width=max(2.2, 2.8 * k),
                          capstyle="round", joinstyle="round", tags="chk")
        else:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["sub"],
                          stipple=self._stip_light, outline="", tags="chk")
            ring = th["accent"] if self._check_hover else th["sub"]
            self._chk_ring = c.create_oval(
                x0 + ring_p, y0 + ring_p, x0 + s - ring_p, y0 + s - ring_p,
                outline=ring, width=2.0, tags="chk")
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
                outline=self.app.theme["accent"] if on
                else self.app.theme["sub"])
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
                         bd=0, bg=th["hover"], fg=th["fg"],
                         insertbackground=th["fg"])
        entry.insert(0, self.todo["text"])
        entry.select_range(0, "end")
        self._edit_win = self.widget.create_window(
            self.text_left, self.height / 2, window=entry, anchor="w",
            width=self.width - self.text_left - self.DEL_RESERVE)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._commit_edit())
        entry.bind("<Escape>", lambda e: self._cancel_edit())
        entry.bind("<FocusOut>", lambda e: self._commit_edit())
        self._edit_entry = entry

    def _commit_edit(self):
        if not self._edit_entry:
            return
        text = self._edit_entry.get().strip()
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


# ---------------- 主程序 ----------------
class TodoApp:
    def __init__(self):
        enable_dpi_awareness()

        self.config = load_json(CONFIG_FILE, {})
        self.todos = load_json(DATA_FILE, [])
        self._next_id = max([t.get("id", 0) for t in self.todos], default=0) + 1
        self.item_widgets = {}
        self._item_wins = {}
        self._resize_mode = None
        self._dragging = False
        self._save_after = None
        self._restack_job = None
        self._heal_job = None
        self._last_cursor = None
        self._last_cw = 0
        self._undo_stack = []
        self._undo_bar = None
        self._undo_after = None
        self._error_bar = None
        self._error_after = None
        self._flash_id = None
        self._clear_armed = False
        self._collapsed = False
        self._last_collapse = 0.0
        self._stipples = {}
        self._font_cache = {}
        self._icon_items = {}
        self._icon_cx = {}
        self.settings_win = None
        self._font_picker = None
        self._add_win = None
        self._glide_jobs = {}
        self._reorder = None
        self._editing_item = None

        self.theme = THEMES.get(self.config.get("theme"), THEMES["亮色"])
        self.font_family = self.config.get("font_family", "微软雅黑")
        self.font_size = int(self.config.get("font_size", 11))
        if self.font_size not in SIZE_CHOICES:
            self.font_size = 11
        self.font_bold = bool(self.config.get("font_bold", False))
        self.chrome_opacity = int(self.config.get("chrome_opacity", 100))
        self.topmost = bool(self.config.get("topmost", True))

        self.root = tk.Tk()
        self.root.title("To-Do List")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        self.root.minsize(MIN_W, MIN_H)
        self.root.geometry(self.config.get("geometry", "320x460+120+120"))
        self.root.configure(bg=KEY)
        try:
            self.root.attributes("-transparentcolor", KEY)
        except Exception:
            pass

        families = sorted(set(tkfont.families()))
        cjk_first = [f for f in families if any("一" <= c <= "鿿" for c in f)]
        self.font_families = cjk_first + [f for f in families if f not in cjk_first]
        if self.font_family not in self.font_families:
            self.font_family = "微软雅黑" if "微软雅黑" in self.font_families \
                else self.font_families[0]
        # 设置页分组标题锁定字体：优先思源宋体，随系统安装情况回退
        self.group_font = next(
            (f for f in ("思源宋体", "Source Han Serif SC",
                         "Source Han Serif CN", "Source Han Serif",
                         "Noto Serif CJK SC", "Noto Serif SC")
             if f in self.font_families),
            "微软雅黑" if "微软雅黑" in self.font_families
            else self.font_families[0])
        # 待办栏位：初始 3 栏，随待办数自动增减，手动调整以栏为单位
        n = len(self.todos)
        self.list_slots = int(self.config.get(
            "list_slots", min(max(n, 3), 10)))

        self._build_ui()
        self._set_slots(self.list_slots, save=False)

        self.root.bind_all("<Motion>", self._cursor_update, add="+")
        self.root.bind_all("<ButtonPress-1>", self._edge_press, add="+")
        self.root.bind_all("<B1-Motion>", self._edge_drag, add="+")
        self.root.bind_all("<ButtonRelease-1>", self._edge_release, add="+")
        self.root.bind("<Escape>", lambda e: None)
        self.root.bind_all("<Control-z>", lambda e: self.undo(), add="+")

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.bind("<Destroy>", self._on_destroy)
        self._heal_job = self.root.after(800, self._heal_autostart)

    # ========== 工具 ==========
    def lerp(self, c1, c2, t):
        a = self.root.winfo_rgb(c1)
        b = self.root.winfo_rgb(c2)
        return "#%02x%02x%02x" % tuple(
            int((a[i] + (b[i] - a[i]) * t) / 256) for i in range(3))

    def _cancel_jobs(self):
        for attr in ("_restack_job", "_save_after", "_undo_after",
                     "_error_after", "_heal_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _on_destroy(self, e):
        if e.widget is self.root:
            self._cancel_jobs()

    def font(self, family, size, weight="normal", overstrike=False):
        """字体缓存：卡片重建/渲染不再重复创建 tkfont.Font。"""
        key = (family, size, weight, overstrike)
        f = self._font_cache.get(key)
        if f is None:
            f = tkfont.Font(family=family, size=size,
                            weight=weight, overstrike=overstrike)
            self._font_cache[key] = f
        return f

    def _stipple_for(self, pct):
        """按透明度生成有序抖动点阵（XBM 文件缓存）。>=96 实心，<4 全透。"""
        if pct >= 96:
            return ""
        key = max(4, int(round(pct / 5.0) * 5))
        if key in self._stipples:
            return self._stipples[key]
        threshold = key * 64 / 100.0
        row_bytes = []
        for y in range(8):
            b = 0
            for x in range(8):
                if _BAYER8[y][x] < threshold:
                    b |= (1 << x)
            row_bytes.append("0x%02x" % b)
        data = ("#define im_width 8\n#define im_height 8\n"
                "static char im_bits[] = {\n   %s};\n" % ", ".join(row_bytes))
        try:
            d = os.path.join(DATA_DIR, "stipples")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "stip_%d.xbm" % key)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    f.write(data)
            ref = "@" + path
        except Exception:
            return ""
        self._stipples[key] = ref
        return ref

    def _apply_chrome(self):
        """透明度套用到窗口底板与所有卡片底色（文字与控件不受影响）。"""
        pct = self.chrome_opacity
        th = self.theme
        stip = self._stipple_for(pct)
        bg_fill = KEY if pct < 4 else th["bg"]
        hd_fill = KEY if pct < 4 else th["header"]
        self.chrome.itemconfig(self.bg_rect, fill=bg_fill, stipple=stip)
        self.chrome.itemconfig(self.header_rect, fill=hd_fill, stipple=stip)
        self.chrome.itemconfig(self.sep_line,
                               fill=(KEY if pct < 4 else th["border"]))
        self.canvas.itemconfig(self.list_bg, fill=bg_fill, stipple=stip)
        for item in list(self.item_widgets.values()):
            try:
                item.apply_surface()
            except Exception:
                pass  # 重建瞬间的旧卡片引用，静默跳过

    # ========== 界面构建 ==========
    def _build_ui(self):
        self._cancel_jobs()
        for w in self.root.winfo_children():
            w.destroy()
        self._undo_bar = None
        self._error_bar = None
        self._stipples = {}
        self._icon_items = {}
        self._icon_cx = {}
        self.item_widgets = {}
        self._item_wins = {}
        self._last_cw = 0
        self._reorder = None
        self._add_win = None
        th = self.theme

        # ---- 底板画布 ----
        self.chrome = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.chrome.pack(fill="both", expand=True)
        self.bg_rect = self.chrome.create_rectangle(0, 0, 1, 1, outline="")
        self.header_rect = self.chrome.create_rectangle(0, 0, 1, HEADER_H,
                                                        outline="")
        self.sep_line = self.chrome.create_line(0, HEADER_H, 1, HEADER_H)

        cy = HEADER_H / 2
        self.chrome.create_oval(16, cy - 6, 28, cy + 6,
                                fill=th["accent"], outline="")
        self.title_item = self.chrome.create_text(
            38, cy, text="To-Do List", anchor="w",
            font=TITLE_FONT, fill=th["header_fg"])
        for name in ("close", "settings", "plus"):
            self._make_icon(name)
        self.grip_item = self.chrome.create_text(
            0, 0, text="◢", anchor="se", fill=th["sub"],
            font=(self.font_family, 10), tags="grip")

        # ---- 滚动列表画布 ----
        self.canvas = tk.Canvas(self.chrome, bg=KEY, highlightthickness=0, bd=0)
        self.list_bg = self.canvas.create_rectangle(0, 0, 1, 1, outline="")
        self.scroll_win = self.chrome.create_window(0, 0, window=self.canvas,
                                                    anchor="nw")
        # 空状态
        self.empty_items = [
            self.canvas.create_oval(0, 0, 56, 56, fill=th["accent"],
                                    outline="", state="hidden"),
            self.canvas.create_line(0, 0, 0, 0, fill="#FFFFFF", width=4,
                                    state="hidden", capstyle="round",
                                    joinstyle="round"),
            self.canvas.create_text(0, 0, text="还没有待办", fill=th["fg"],
                                    state="hidden",
                                    font=(self.font_family,
                                          self.font_size + 2, "bold")),
            self.canvas.create_text(0, 0, text="点击右上角 ＋ 新建第一条吧",
                                    fill=th["sub"], state="hidden",
                                    font=(self.font_family, self.font_size)),
        ]
        # ---- 事件 ----
        self.chrome.bind("<Configure>", self._layout)
        self.chrome.bind("<Motion>", self._chrome_motion)
        self.chrome.bind("<ButtonPress-1>", self._chrome_press)
        self.chrome.bind("<B1-Motion>", self._chrome_drag)
        self.chrome.bind("<ButtonRelease-1>", self._chrome_release)
        self.chrome.bind("<Double-Button-1>", self._chrome_dblclick)
        self.canvas.bind("<Configure>", self._on_scroll_configure)
        self._bind_wheel(self.canvas)

        self._last_layout_size = None
        self._apply_chrome()
        self.render_items()
        self.root.update_idletasks()
        self._layout(force=True)
        # 重建后列表尺寸此时尚未生效，待首个 Configure 落定后强制重排一次，
        # 防止卡片停留在未布局状态（切字号/主题后待办消失的根因之一）
        self.canvas.yview_moveto(0)
        self.root.after_idle(self._fire_restack)

    # ---------- 矢量图标 ----------
    def _make_icon(self, name):
        color = self.theme["header_fg"]
        items = []
        s = 9
        if name == "plus":
            items.append(self.chrome.create_line(
                -s, 0, s, 0, fill=color, width=2.6, capstyle="round"))
            items.append(self.chrome.create_line(
                0, -s, 0, s, fill=color, width=2.6, capstyle="round"))
        elif name == "close":
            items.append(self.chrome.create_line(
                -s, -s, s, s, fill=color, width=2.6, capstyle="round"))
            items.append(self.chrome.create_line(
                -s, s, s, -s, fill=color, width=2.6, capstyle="round"))
        elif name == "settings":
            # 滑杆式设置图标：三条横线 + 错位旋钮，不会被误认为太阳
            for ly, kx in ((-8, -4), (0, 5), (8, -1)):
                items.append(self.chrome.create_line(
                    -9, ly, 9, ly, fill=color, width=2.2, capstyle="round"))
                items.append(self.chrome.create_oval(
                    kx - 3.4, ly - 3.4, kx + 3.4, ly + 3.4,
                    fill=color, outline=""))
        for it in items:
            self.chrome.addtag_withtag("btn", it)
            self.chrome.addtag_withtag("btn_" + name, it)
        self._icon_items[name] = items
        self._icon_cx[name] = (0, 0)
        cmd = {"plus": self._open_add_dialog, "settings": self._open_settings,
               "close": self._quit}[name]
        self.chrome.tag_bind("btn_" + name, "<Button-1>",
                             lambda e, c=cmd: c())
        self.chrome.tag_bind("btn_" + name, "<Enter>",
                             lambda e, n=name: self._icon_color(n, True))
        self.chrome.tag_bind("btn_" + name, "<Leave>",
                             lambda e, n=name: self._icon_color(n, False))

    def _icon_color(self, name, hover):
        color = self.theme["accent"] if hover else self.theme["header_fg"]
        for it in self._icon_items.get(name, []):
            if self.chrome.type(it) == "oval":
                self.chrome.itemconfig(it, fill=color, outline=color)
            else:
                self.chrome.itemconfig(it, fill=color)

    def _move_icon(self, name, cx, cy):
        ox, oy = self._icon_cx.get(name, (0, 0))
        for it in self._icon_items.get(name, []):
            self.chrome.move(it, cx - ox, cy - oy)
        self._icon_cx[name] = (cx, cy)

    # ---------- 布局 ----------
    def _layout(self, _e=None, force=False):
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        # 窗口移动（位置变、尺寸不变）也会触发 Configure：
        # 尺寸没变就跳过重排，消除拖动窗口时的整屏闪烁
        if not force and (W, H) == self._last_layout_size:
            return
        self._last_layout_size = (W, H)
        self.chrome.coords(self.bg_rect, 0, 0, W, H)
        self.chrome.coords(self.header_rect, 0, 0, W, HEADER_H)
        self.chrome.coords(self.sep_line, 0, HEADER_H, W, HEADER_H)
        cy = HEADER_H / 2
        for name, cx in (("close", W - 30), ("settings", W - 80),
                         ("plus", W - 130)):
            self._move_icon(name, cx, cy)
        if self._collapsed:
            self.chrome.itemconfig(self.grip_item, state="hidden")
            self.chrome.itemconfig(self.scroll_win, state="hidden")
        else:
            self.chrome.itemconfig(self.grip_item, state="normal")
            self.chrome.coords(self.grip_item, W - 10, H - 8)
            list_y = HEADER_H + 8
            self.chrome.itemconfig(self.scroll_win, state="normal")
            self.chrome.coords(self.scroll_win, 14, list_y)
            self.chrome.itemconfig(self.scroll_win, width=W - 28,
                                   height=max(40, H - list_y - 26))

    # ---------- 列表内部布局 ----------
    def _on_scroll_configure(self, e):
        """纯纵向变化：O(1) 坐标更新，零重排。
        宽度变化：卡片边框即时跟随（廉价），文字重排防抖。"""
        self.canvas.coords(self.list_bg, 0, 0, e.width, e.height)
        self._layout_empty()
        if e.width != self._last_cw:
            self._last_cw = e.width
            cw = max(120, e.width - 2)
            for item in self.item_widgets.values():
                try:
                    item.set_frame_width(cw)
                except Exception:
                    pass  # 防抖期间被销毁的旧卡片
            for win in self._item_wins.values():
                self.canvas.itemconfig(win, width=cw)
            if self._restack_job:
                self.root.after_cancel(self._restack_job)
            self._restack_job = self.root.after(80, self._fire_restack)

    def _fire_restack(self):
        self._restack_job = None
        self._restack()

    def _restack(self):
        """重排卡片：设置文字宽度 -> 量高 -> 堆叠 -> 滚动区域。"""
        w = self.canvas.winfo_width()
        if w <= 1:
            return
        cw = max(120, w - 2)
        ordered_ids = self._ordered_ids()
        for tid in ordered_ids:
            item = self.item_widgets.get(tid)
            if item:
                try:
                    item.set_width(cw)
                except Exception:
                    pass  # 防抖期间被销毁的旧卡片
        self.root.update_idletasks()
        y = 0
        for tid in ordered_ids:
            item = self.item_widgets.get(tid)
            win = self._item_wins.get(tid)
            if not item or not win:
                continue
            try:
                h = item.measure()
            except Exception:
                continue
            item.layout(cw, h)
            self.canvas.itemconfig(win, width=cw, height=h)
            self.canvas.coords(win, 0, y)
            y += h + 8
        self.canvas.configure(scrollregion=(0, 0, w, max(y - 8, 1)))

    def _raise_card(self, tid):
        """把卡片置顶：整体重建该卡片的控件。
        新创建的子窗口必然位于所有同级窗口之上（各平台铁律），
        不依赖 Windows 对画布内嵌窗口的层级重排（实测不可靠）。"""
        todo = next((t for t in self.todos if t["id"] == tid), None)
        old = self.item_widgets.get(tid)
        win = self._item_wins.get(tid)
        if not todo or not old or win is None:
            return win
        try:
            x, y = self.canvas.coords(win)
            w = int(float(self.canvas.itemcget(win, "width")))
            h = int(float(self.canvas.itemcget(win, "height")))
        except Exception:
            return win
        try:
            self.canvas.delete(win)
            old.widget.destroy()
            item = TodoItem(self, todo)  # 全新子窗口 = 原生最顶层
            item.set_width(w)
            item.layout(w, h)
            self.item_widgets[tid] = item
            new_win = self.canvas.create_window(
                x, y, window=item.widget, anchor="nw",
                width=w, height=h)
            self._item_wins[tid] = new_win
            self._bind_wheel(item.widget)
            return new_win
        except Exception:
            return win

    def _make_proxy(self, item, w, h):
        """拖拽替身：极简子窗口快照（新建子窗口天然位于同级最顶层）。
        只画底框+圆圈+文字，不建按钮/字体/点阵查找，建造成本极低，
        避免拖动起步时整卡重建造成的卡顿。"""
        c = tk.Canvas(self.canvas, bg=KEY, bd=0, highlightthickness=0,
                      width=w, height=h)
        # 底框直接快照真身当前的填充/点阵/描边，观感一致
        try:
            fill = item.widget.itemcget(item.rect, "fill")
            stip = item.widget.itemcget(item.rect, "stipple")
            outline = item.widget.itemcget(item.rect, "outline")
        except Exception:
            fill, stip, outline = self.theme["item"], "", ""
        c.create_rectangle(0, 0, w, h, fill=fill, stipple=stip,
                           outline=outline, width=1)
        th = self.theme
        done = item.todo.get("done", False)
        # 勾选圈与真身 _draw_check 完全一致（含点阵填充与白色对勾）
        s = item.check_size
        x0, y0 = item.LEFT, (h - s) / 2
        ring_p = 2.2
        fill_p = ring_p + 2.4
        if done:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["accent"],
                          stipple=item._stip_dense, outline="")
            c.create_oval(x0 + ring_p, y0 + ring_p, x0 + s - ring_p,
                          y0 + s - ring_p, outline=th["accent"], width=2.2)
            k = s / 26.0
            pts = [x0 + 7.2 * k, y0 + 13.2 * k, x0 + 11.2 * k, y0 + 17.0 * k,
                   x0 + 18.8 * k, y0 + 7.8 * k]
            c.create_line(*pts, fill="#FFFFFF", width=max(2.2, 2.8 * k),
                          capstyle="round", joinstyle="round")
        else:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["sub"],
                          stipple=item._stip_light, outline="")
            ring = th["accent"] if item._check_hover else th["sub"]
            c.create_oval(x0 + ring_p, y0 + ring_p, x0 + s - ring_p,
                          y0 + s - ring_p, outline=ring, width=2.0)
        c.create_text(item.text_left, h / 2, anchor="w",
                      text=item.todo["text"],
                      font=item.font_done if done else item.font_normal,
                      fill=th["sub"] if done else th["fg"],
                      width=w - item.text_left - item.DEL_RESERVE)
        return c

    # ---------- 顺序模型 ----------
    def _ordered_ids(self):
        """视觉顺序：未完成在前（seq 升序），已完成沉底。"""
        return [t["id"] for t in sorted(
            self.todos,
            key=lambda x: (x.get("done", False), x.get("seq", x.get("id", 0))))]

    # ---------- 卡片滑动动画 ----------
    def _glide_win(self, win, y2, ms=130, done=None):
        """缓出滑动：15ms 一帧（~67fps），cubic ease-out，绝不逐帧卡顿。"""
        old = self._glide_jobs.get(win)
        if old:
            try:
                self.root.after_cancel(old)
            except Exception:
                pass
        try:
            y1 = self.canvas.coords(win)[1]
        except Exception:
            return
        steps = max(2, ms // 15)

        def step(i):
            try:
                t = i / steps
                ease = 1 - (1 - t) ** 3
                self.canvas.coords(win, 0, y1 + (y2 - y1) * ease)
            except Exception:
                self._glide_jobs.pop(win, None)
                return
            if i < steps:
                self._glide_jobs[win] = self.root.after(15, lambda: step(i + 1))
            else:
                self._glide_jobs.pop(win, None)
                if done:
                    done()
        step(1)

    def _animate_restack(self, moved_tid=None):
        """勾选/取消勾选后：卡片滑动到新堆叠位置（沉底/回升）。
        滑动中的卡片置顶，从其他卡片上方掠过。"""
        w = self.canvas.winfo_width()
        if w <= 1:
            self.render_items()
            return
        if moved_tid is not None and moved_tid in self._item_wins:
            self._raise_card(moved_tid)  # 滑动卡片单独位于最顶层
        order = self._ordered_ids()
        y = 0
        targets = {}
        for tid in order:
            item = self.item_widgets.get(tid)
            if not item:
                continue
            targets[tid] = y
            y += item.height + 8
        for tid, ty in targets.items():
            win = self._item_wins.get(tid)
            if win is None:
                continue
            try:
                cur = self.canvas.coords(win)[1]
            except Exception:
                continue
            if abs(cur - ty) >= 1:
                self._glide_win(win, ty, ms=150)
        self.canvas.configure(scrollregion=(0, 0, w, max(y - 8, 1)))

    # ---------- 长按拖动排序 ----------
    def _begin_reorder(self, item):
        """进入排序：真身移出视野，拖一个极简替身窗口（新窗口天然最顶层），
        不重建卡片控件，拖动起步零卡顿；记录视觉顺序与各卡槽位。"""
        press_y_root = item._press_y_root
        real_win = self._item_wins.get(item.todo["id"])
        if real_win is None:
            return
        try:
            x, y = self.canvas.coords(real_win)
            w = int(float(self.canvas.itemcget(real_win, "width")))
            h = int(float(self.canvas.itemcget(real_win, "height")))
        except Exception:
            return
        self.canvas.coords(real_win, -3000, 0)  # 真身原地保留，移出视野
        proxy = self._make_proxy(item, w, h)
        win = self.canvas.create_window(x, y, window=proxy, anchor="nw",
                                        width=w, height=h)
        order = self._ordered_ids()
        ys = {}
        y = 0
        for tid in order:
            it = self.item_widgets.get(tid)
            if not it:
                continue
            ys[tid] = y
            y += it.height + 8
        # 按压点即抓取点：第一次位移就生效，不会吞掉初始跳变
        grab = None
        try:
            py = self.canvas.canvasy(press_y_root - self.canvas.winfo_rooty())
            grab = py - self.canvas.coords(win)[1]
        except Exception:
            pass
        self._reorder = {"item": item, "win": win, "order": order,
                         "ys": ys, "grab": grab, "proxy": proxy}
        # 拖动中指针可能落在卡片间隙：列表画布接力 motion/release
        self.canvas.bind("<B1-Motion>",
                         lambda e: self._reorder_motion(e.y_root))
        self.canvas.bind("<ButtonRelease-1>",
                         lambda e: self._commit_reorder())

    def _reorder_motion(self, y_root):
        r = self._reorder
        if not r:
            return
        item = r["item"]
        py = self.canvas.canvasy(y_root - self.canvas.winfo_rooty())
        win = r["win"]
        if r["grab"] is None:
            try:
                r["grab"] = py - self.canvas.coords(win)[1]
            except Exception:
                return
        new_y = py - r["grab"]
        self.canvas.coords(win, 0, new_y)
        tid = item.todo["id"]
        done_flag = item.todo.get("done", False)
        order = r["order"]
        center = new_y + item.height / 2
        # 仅与同组（未完成/已完成）相邻卡片交换；while 循环支持一次
        # 大幅度拖动跨越多张卡片（快速甩动鼠标时不会丢交换）
        idx = order.index(tid)
        while idx > 0:
            o_tid = order[idx - 1]
            other = self.item_widgets.get(o_tid)
            if not other or other.todo.get("done", False) != done_flag:
                break
            if center >= r["ys"][o_tid] + other.height / 2:
                break
            order[idx - 1], order[idx] = order[idx], order[idx - 1]
            self._shift_after_swap(order, o_tid)
            idx -= 1
        idx = order.index(tid)
        while idx < len(order) - 1:
            o_tid = order[idx + 1]
            other = self.item_widgets.get(o_tid)
            if not other or other.todo.get("done", False) != done_flag:
                break
            if center <= r["ys"][o_tid] + other.height / 2:
                break
            order[idx + 1], order[idx] = order[idx], order[idx + 1]
            self._shift_after_swap(order, o_tid)
            idx += 1

    def _shift_after_swap(self, order, moved_tid):
        """交换后重算槽位，被挤开的卡片滑动让位。"""
        y = 0
        for tid in order:
            it = self.item_widgets.get(tid)
            if not it:
                continue
            self._reorder["ys"][tid] = y
            y += it.height + 8
        if moved_tid != self._reorder["item"].todo["id"]:
            win = self._item_wins.get(moved_tid)
            if win is not None:
                self._glide_win(win, self._reorder["ys"][moved_tid], ms=110)

    def _commit_reorder(self):
        r = self._reorder
        if not r:
            return
        self._reorder = None
        self.canvas.unbind("<B1-Motion>")
        self.canvas.unbind("<ButtonRelease-1>")
        item = r["item"]
        order = r["order"]
        # 槽位落定
        y = 0
        final = {}
        for tid in order:
            it = self.item_widgets.get(tid)
            if not it:
                continue
            final[tid] = y
            y += it.height + 8
        dragged_win = r["win"]
        tid = item.todo["id"]

        def finish():
            # 销毁替身（真身随 render_items 一并重建）
            try:
                self.canvas.delete(dragged_win)
                r["proxy"].destroy()
            except Exception:
                pass
            # 写回顺序（seq 即视觉索引），保存并重排
            by_id = {t["id"]: t for t in self.todos}
            for i, t_id in enumerate(order):
                if t_id in by_id:
                    by_id[t_id]["seq"] = i
            self._save_todos()
            self.render_items()

        if tid in final:
            self._glide_win(dragged_win, final[tid], ms=120, done=finish)
        else:
            finish()

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._wheel)
        widget.bind("<Button-4>", lambda e: self._wheel_dir(-1))
        widget.bind("<Button-5>", lambda e: self._wheel_dir(1))
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _wheel(self, e):
        self._wheel_dir(-1 if e.delta > 0 else 1)

    def _wheel_dir(self, d):
        self.canvas.yview_scroll(d, "units")

    def _layout_empty(self):
        if self.todos:
            for it in self.empty_items:
                self.canvas.itemconfig(it, state="hidden")
            return
        w = max(self.canvas.winfo_width(), 200)
        h = max(self.canvas.winfo_height(), 200)
        cx, cy = w / 2, h * 0.28
        self.canvas.coords(self.empty_items[0],
                           cx - 28, cy - 28, cx + 28, cy + 28)
        self.canvas.coords(self.empty_items[1],
                           cx - 11, cy, cx - 3, cy + 9, cx + 12, cy - 11)
        self.canvas.coords(self.empty_items[2], cx, cy + 52)
        self.canvas.coords(self.empty_items[3], cx, cy + 78)
        for it in self.empty_items:
            self.canvas.itemconfig(it, state="normal")

    # ---------- 栏位高度体系 ----------
    def _slot_h(self):
        """单个栏位高度 = 单行卡片高度 + 卡片间距。"""
        f = tkfont.Font(family=self.font_family, size=self.font_size,
                        weight="bold" if self.font_bold else "normal")
        line = f.metrics("linespace")
        item_h = max(line, max(26, self.font_size + 14)) + TodoItem.PAD * 2
        return item_h + 8

    def _slots_height(self, slots):
        return slots * self._slot_h() - 8

    def _height_for_slots(self, slots):
        return HEADER_H + 8 + self._slots_height(slots) + 26

    def _set_slots(self, slots, save=True):
        """以栏位为单位设置窗口高度（3~10 栏）。"""
        slots = min(max(int(slots), 3), 10)
        self.list_slots = slots
        if not self._collapsed:
            h = self._height_for_slots(slots)
            self.root.geometry(f"{self.root.winfo_width()}x{h}")
        if save:
            self._schedule_save()

    def _auto_slots(self):
        """待办数变化时：栏位自动跟随（3 起步，10 封顶）。"""
        self._set_slots(min(max(len(self.todos), 3), 10))

    # ---------- 新建待办弹窗（与设置弹窗同风格） ----------
    def _open_add_dialog(self):
        if self._add_win:
            try:
                if self._add_win.winfo_exists():
                    self._add_win.lift()
                    self._add_win.focus_force()
                    return
            except Exception:
                pass
            self._add_win = None
        if self._collapsed:
            self._toggle_collapse()
        th = self.theme
        win = tk.Toplevel(self.root)
        self._add_win = win
        win.withdraw()  # 先隐藏，定位后再显示，杜绝闪位
        win.title("新建待办")
        win.resizable(False, False)
        win.configure(bg=th["border"])
        win.transient(self.root)
        if self.topmost:
            win.attributes("-topmost", True)
        body = tk.Frame(win, bg=th["panel"], highlightthickness=0, bd=0)
        body.pack(padx=1, pady=1)
        inner = tk.Frame(body, bg=th["panel"])
        inner.pack(padx=16, pady=14)
        tk.Label(inner, text="新建待办", bg=th["panel"], fg=th["accent"],
                 font=(self.group_font, self.font_size, "bold")).pack(
            anchor="w")
        entry = tk.Entry(inner, width=30, relief="flat", bd=0,
                         bg=th["hover"], fg=th["fg"],
                         insertbackground=th["fg"],
                         font=(self.font_family, self.font_size + 1))
        entry.pack(fill="x", ipady=7, pady=(8, 4))
        tk.Label(inner, text="回车添加 · Esc 取消", bg=th["panel"],
                 fg=th["sub"], font=(self.font_family, self.font_size)).pack(
            anchor="w")

        def commit(_e=None):
            text = entry.get().strip()
            if text:
                self._add_todo_text(text)
            close()

        def close(_e=None):
            try:
                if win.winfo_exists():
                    win.destroy()
            except Exception:
                pass
            self._add_win = None

        entry.bind("<Return>", commit)
        entry.bind("<Escape>", close)
        win.bind("<FocusOut>", lambda e: win.after(
            150, lambda: self._close_add_if_unfocused(win)))
        win.protocol("WM_DELETE_WINDOW", close)
        # 定位：标题栏正下方、右对齐组件（加号键脚下）
        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_x() + self.root.winfo_width() - ww
        y = self.root.winfo_y() + HEADER_H + 8
        x = min(max(0, x), win.winfo_screenwidth() - ww - 8)
        y = min(max(0, y), win.winfo_screenheight() - wh - 8)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
        win.deiconify()
        win.lift(self.root)
        entry.focus_set()
        win.after(60, lambda: win.winfo_exists() and entry.focus_force())

    def _close_add_if_unfocused(self, win):
        try:
            if win.winfo_exists() and win.focus_get() is None:
                win.destroy()
                if self._add_win is win:
                    self._add_win = None
        except Exception:
            pass

    # ---------- 折叠 ----------
    def _toggle_collapse(self, _e=None):
        import time as _t
        now = _t.time()
        if now - self._last_collapse < 0.35:
            return  # 去抖：快速连续双击只算一次，防止折叠/展开来回闪烁
        self._last_collapse = now
        self._dragging = False
        self._resize_mode = None
        if self._collapsed:
            self._collapsed = False
            self.root.minsize(MIN_W, MIN_H)
            h = self._height_for_slots(self.list_slots)
            self.root.geometry(f"{self.root.winfo_width()}x{h}")
        else:
            self._collapsed = True
            self.root.minsize(MIN_W, HEADER_H + 1)
            self.root.geometry(f"{self.root.winfo_width()}x{HEADER_H + 1}")
        self._layout(force=True)
        self._schedule_save()

    # ========== 设置弹窗（独立静态窗口） ==========
    def _open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        th = self.theme
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.withdraw()  # 先隐藏：构建+定位完成后才显示，窗口永不闪现在错误位置
        win.title("设置")
        win.resizable(False, False)
        win.configure(bg=th["panel"])
        win.transient(self.root)
        if self.topmost:
            win.attributes("-topmost", True)
        body = tk.Frame(win, bg=th["panel"])
        body.pack(padx=18, pady=(8, 14))

        def group(title):
            # 分组标题：锁定思源宋体（加粗），字号随设置
            tk.Label(body, text=title, bg=th["panel"], fg=th["accent"],
                     font=(self.group_font, self.font_size, "bold")).pack(
                anchor="w", pady=(12, 2))

        def row(label):
            f = tk.Frame(body, bg=th["panel"])
            f.pack(fill="x", pady=7)
            tk.Label(f, text=label, bg=th["panel"], fg=th["fg"],
                     font=(self.font_family, self.font_size)).pack(side="left")
            return f

        def pill(parent, text, selected, cmd):
            bg = th["accent"] if selected else th["hover"]
            fg = "#FFFFFF" if selected else th["fg"]
            p = tk.Label(parent, text=text, bg=bg, fg=fg,
                         font=(self.font_family, self.font_size),
                         padx=10, pady=3)
            clickable(p)
            p.pack(side="right", padx=2)
            p.bind("<Button-1>", lambda e: cmd())
            return p

        group("外观")

        r = row("透明度")
        pct_label = tk.Label(r, text=f"{self.chrome_opacity}%",
                             bg=th["panel"], fg=th["fg"], width=4,
                             font=(self.font_family, self.font_size, "bold"))
        pct_label.pack(side="right")
        scale = tk.Scale(
            r, from_=0, to=100, orient="horizontal", showvalue=False,
            length=190, width=14, sliderlength=24, sliderrelief="flat",
            bg=th["panel"], fg=th["fg"], highlightthickness=0, bd=0,
            troughcolor=th["border"], activebackground=th["accent"],
            command=lambda v: self._set_chrome(int(v), pct_label))
        scale.set(self.chrome_opacity)
        scale.pack(side="right", padx=(8, 4))
        tk.Label(body, text="底板与卡片底色淡出，待办文字始终清晰",
                 bg=th["panel"], fg=th["sub"],
                 font=(self.font_family, self.font_size)).pack(anchor="w")

        r = row("主题")
        for name in THEMES:
            pill(r, name, name == self._theme_name(),
                 lambda n=name: self._set_theme(n))

        r = row("字体")
        bold_wrap = tk.Frame(r, bg=th["panel"])
        bold_wrap.pack(side="right", padx=(8, 0))
        tk.Label(bold_wrap, text="加粗", bg=th["panel"], fg=th["fg"],
                 font=(self.font_family, self.font_size)).pack(side="left",
                                                               padx=(0, 6))
        Switch(bold_wrap, on=self.font_bold, command=self._apply_bold,
               accent=th["accent"], bg=th["panel"]).pack(side="left")
        # 自绘字体选择按钮 + 全主题化弹出列表，任何主题下文字都清晰
        font_btn = tk.Label(r, text=self.font_family + "  ▾",
                            bg=th["hover"], fg=th["fg"], padx=10, pady=3,
                            font=(self.font_family, self.font_size))
        clickable(font_btn)
        font_btn.pack(side="right")
        font_btn.bind("<Button-1>",
                      lambda e: self._open_font_picker(font_btn))

        r = row("字号")
        for s in reversed(SIZE_CHOICES):
            pill(r, str(s), s == self.font_size,
                 lambda v=s: self._set_font(None, v, None))

        group("行为")
        r = row("窗口置顶")
        Switch(r, on=self.topmost, command=self._apply_topmost,
               accent=th["accent"], bg=th["panel"]).pack(side="right")
        r = row("开机自动启动")
        Switch(r, on=get_autostart(), command=self._apply_autostart,
               accent=th["accent"], bg=th["panel"]).pack(side="right")

        group("数据")
        r = row("清理")
        self.clear_btn = tk.Label(r, text="清除已完成事项", bg=th["panel"],
                                  fg=th["accent"],
                                  font=(self.font_family, self.font_size),
                                  padx=6, pady=2)
        clickable(self.clear_btn)
        self.clear_btn.pack(side="right")
        self.clear_btn.bind("<Button-1>", self._clear_done_click)
        r = row("数据目录")
        open_btn = tk.Label(r, text="打开数据文件夹", bg=th["panel"],
                            fg=th["accent"],
                            font=(self.font_family, self.font_size),
                            padx=6, pady=2)
        clickable(open_btn)
        open_btn.pack(side="right")
        open_btn.bind("<Button-1>", lambda e: self._open_data_dir())

        # 定位（窗口仍处于隐藏状态）：设置键附近——标题栏正下方、右对齐
        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_x() + self.root.winfo_width() - ww
        y = self.root.winfo_y() + HEADER_H + 8
        x = min(max(0, x), win.winfo_screenwidth() - ww - 8)
        y = min(max(0, y), win.winfo_screenheight() - wh - 8)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Escape>", lambda e: win.destroy())
        # 一步到位显示在最终位置，并获得焦点（标题栏激活态）
        win.deiconify()
        win.lift(self.root)
        win.focus_set()
        win.after(60, lambda: win.winfo_exists() and win.focus_force())

    def _open_font_picker(self, anchor):
        """全主题化字体下拉：背景/文字/选中色全部显式指定，杜绝主题切换后看不清。"""
        if self._font_picker:
            try:
                if self._font_picker.winfo_exists():
                    self._font_picker.destroy()
                    self._font_picker = None
                    return
            except Exception:
                pass
            self._font_picker = None
        th = self.theme
        win = tk.Toplevel(self.root)
        self._font_picker = win
        win.overrideredirect(True)
        win.configure(bg=th["border"])
        if self.topmost:
            win.attributes("-topmost", True)
        body = tk.Frame(win, bg=th["panel"], highlightthickness=0, bd=0)
        body.pack(padx=1, pady=1)
        sb = tk.Scrollbar(body, orient="vertical", bg=th["hover"],
                          troughcolor=th["panel"], bd=0,
                          highlightthickness=0, width=10,
                          activebackground=th["accent"])
        lb = tk.Listbox(
            body, height=12, width=22,
            font=(self.font_family, self.font_size),
            bg=th["panel"], fg=th["fg"],
            selectbackground=th["accent"], selectforeground="#FFFFFF",
            relief="flat", highlightthickness=0, bd=0,
            activestyle="none", exportselection=False,
            yscrollcommand=sb.set)
        sb.config(command=lb.yview)
        for f in self.font_families:
            lb.insert("end", f)
        try:
            idx = self.font_families.index(self.font_family)
        except ValueError:
            idx = 0
        lb.selection_set(idx)
        lb.activate(idx)
        lb.see(max(0, idx - 3))
        lb.pack(side="left", fill="both")
        sb.pack(side="right", fill="y")
        lb.bind("<MouseWheel>",
                lambda e: lb.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        lb.bind("<Button-4>", lambda e: lb.yview_scroll(-1, "units"))
        lb.bind("<Button-5>", lambda e: lb.yview_scroll(1, "units"))

        def pick(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            fam = lb.get(sel[0])
            try:
                win.destroy()
            except Exception:
                pass
            self._font_picker = None
            self._set_font(fam, None, None)

        lb.bind("<ButtonRelease-1>", pick)
        lb.bind("<Return>", pick)
        lb.bind("<Escape>", lambda e: win.destroy())
        win.bind("<FocusOut>", lambda e: win.after(
            150, lambda: self._close_picker_if_unfocused(win)))
        win.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        x = min(max(0, x), win.winfo_screenwidth() - win.winfo_width() - 8)
        y = min(max(0, y), win.winfo_screenheight() - win.winfo_height() - 8)
        win.geometry(f"+{x}+{y}")
        lb.focus_set()

    def _close_picker_if_unfocused(self, win):
        try:
            if win.winfo_exists() and win.focus_get() is None:
                win.destroy()
                if self._font_picker is win:
                    self._font_picker = None
        except Exception:
            pass

    def _close_settings(self):
        if self._font_picker:
            try:
                if self._font_picker.winfo_exists():
                    self._font_picker.destroy()
            except Exception:
                pass
            self._font_picker = None
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.destroy()
        self.settings_win = None

    # ========== 待办操作 ==========
    def render_items(self):
        for item in self.item_widgets.values():
            item.widget.destroy()
        self.item_widgets.clear()
        self._item_wins.clear()
        self._editing_item = None
        ordered_ids = self._ordered_ids()
        by_id = {t["id"]: t for t in self.todos}
        for t in (by_id[i] for i in ordered_ids if i in by_id):
            item = TodoItem(self, t)
            # 先在屏外创建：restack 中途的重绘不会把未归位的卡片
            # 画在标题下方（添加/删除时第一条虚影的根因）
            win = self.canvas.create_window(-3000, 0, window=item.widget,
                                            anchor="nw")
            self.item_widgets[t["id"]] = item
            self._item_wins[t["id"]] = win
            self._bind_wheel(item.widget)
            if t["id"] == self._flash_id:
                item.flash()
        self._flash_id = None
        self._restack()
        self._layout_empty()

    def _save_todos(self):
        if not save_json(DATA_FILE, self.todos):
            self._show_error("待办保存失败，请检查磁盘权限")

    def _add_todo_text(self, text):
        self.todos.append({"id": self._next_id, "text": text,
                           "done": False, "seq": self._next_id})
        self._flash_id = self._next_id
        self._next_id += 1
        self._save_todos()
        self.render_items()
        self.canvas.yview_moveto(1.0)
        self._auto_slots()

    def update_todo_text(self, todo_id, text):
        for t in self.todos:
            if t["id"] == todo_id:
                t["text"] = text
        self._save_todos()
        self.render_items()

    def toggle_todo(self, todo_id, done):
        for t in self.todos:
            if t["id"] == todo_id:
                t["done"] = done
        self._save_todos()
        self._animate_restack(moved_tid=todo_id)  # 平滑滑动沉底/回升

    def delete_todo(self, todo_id):
        for i, t in enumerate(self.todos):
            if t["id"] == todo_id:
                self._undo_stack.append(("delete", t, i))
                break
        self.todos = [t for t in self.todos if t["id"] != todo_id]
        self._save_todos()
        self.render_items()
        self._auto_slots()
        self._show_undo("已删除 1 条")

    def _clear_done_click(self, _e=None):
        if self._clear_armed:
            self._clear_armed = False
            self.clear_btn.config(text="清除已完成事项", fg=self.theme["accent"])
            removed = [t for t in self.todos if t.get("done")]
            if removed:
                self._undo_stack.append(("clear_done", removed))
                self.todos = [t for t in self.todos if not t.get("done")]
                self._save_todos()
                self.render_items()
                self._auto_slots()
                self._show_undo(f"已清除 {len(removed)} 条已完成")
        else:
            self._clear_armed = True
            self.clear_btn.config(text="确认清除？", fg="#E5534B")
            self.root.after(3000, self._disarm_clear)

    def _disarm_clear(self):
        if self._clear_armed:
            self._clear_armed = False
            try:
                self.clear_btn.config(text="清除已完成事项",
                                      fg=self.theme["accent"])
            except Exception:
                pass

    def undo(self, _e=None):
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        if action[0] == "delete":
            _, todo, index = action
            self.todos.insert(min(index, len(self.todos)), todo)
        elif action[0] == "clear_done":
            self.todos.extend(action[1])
        self._save_todos()
        self.render_items()
        self._auto_slots()
        self._hide_undo()

    # ---------- 浮动提示条 ----------
    def _show_undo(self, text):
        self._hide_undo()
        th = self.theme
        bar = tk.Frame(self.root, bg=th["panel"],
                       highlightbackground=th["border"],
                       highlightthickness=1, bd=0)
        tk.Label(bar, text=text, bg=th["panel"], fg=th["fg"],
                 font=(self.font_family, self.font_size)).pack(
            side="left", padx=(14, 8), pady=8)
        btn = tk.Label(bar, text="撤销", bg=th["panel"], fg=th["accent"],
                       font=(self.font_family, self.font_size, "bold"),
                       padx=8, pady=4)
        clickable(btn)
        btn.pack(side="left", padx=(0, 10))
        btn.bind("<Button-1>", lambda e: (self.undo(), self._hide_undo()))
        btn.bind("<Enter>", lambda e: btn.config(bg=th["hover"]))
        btn.bind("<Leave>", lambda e: btn.config(bg=th["panel"]))
        bar.place(relx=0.5, rely=1.0, x=0, y=-12, anchor="s")
        bar.lift()
        self._undo_bar = bar
        self._undo_after = self.root.after(4000, self._hide_undo)

    def _hide_undo(self):
        if self._undo_after:
            try:
                self.root.after_cancel(self._undo_after)
            except Exception:
                pass
            self._undo_after = None
        if self._undo_bar:
            try:
                self._undo_bar.destroy()
            except Exception:
                pass
            self._undo_bar = None

    def _show_error(self, text):
        if self._error_bar:
            try:
                self._error_bar.destroy()
            except Exception:
                pass
        if self._error_after:
            try:
                self.root.after_cancel(self._error_after)
            except Exception:
                pass
        bar = tk.Frame(self.root, bg="#E5534B")
        tk.Label(bar, text=text, bg="#E5534B", fg="#FFFFFF",
                 font=(self.font_family, self.font_size),
                 padx=14, pady=7).pack()
        bar.place(relx=0.5, y=HEADER_H + 10, anchor="n")
        bar.lift()
        self._error_bar = bar
        self._error_after = self.root.after(
            4000, lambda: (self._error_bar and self._error_bar.destroy()))

    # ========== 设置变更 ==========
    def _set_chrome(self, val, pct_label=None):
        self.chrome_opacity = int(val)
        if pct_label is not None:
            pct_label.config(text=f"{self.chrome_opacity}%")
        self._apply_chrome()
        self._schedule_save()

    def _theme_name(self):
        for name, t in THEMES.items():
            if t is self.theme:
                return name
        return "亮色"

    def _rebuild(self):
        settings_open = bool(self.settings_win and
                             self.settings_win.winfo_exists())
        self._build_ui()
        self._set_slots(self.list_slots, save=False)  # 字号变化后栏位重算
        if settings_open:
            self._close_settings()
            self._open_settings()

    def _set_theme(self, name):
        self.theme = THEMES[name]
        self._rebuild()
        self._save_config()

    def _set_font(self, family, size, bold):
        new = (family or self.font_family, size or self.font_size,
               self.font_bold if bold is None else bold)
        if new == (self.font_family, self.font_size, self.font_bold):
            return  # 无变化不重建，避免快速连点时的无谓刷新
        self.font_family, self.font_size, self.font_bold = new
        self._rebuild()
        self._save_config()

    def _apply_bold(self, on):
        self._set_font(None, None, on)

    def _apply_topmost(self, on):
        self.topmost = on
        self.root.attributes("-topmost", on)
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.attributes("-topmost", on)
        self._save_config()

    def _apply_autostart(self, on):
        if not set_autostart(on):
            self._show_error("开机自启设置失败")

    def _heal_autostart(self):
        self._heal_job = None
        val = get_autostart_value()
        if val and os.path.abspath(__file__).lower() not in val.lower():
            set_autostart(True)

    def _open_data_dir(self):
        try:
            if hasattr(os, "startfile"):
                os.startfile(DATA_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", DATA_DIR])
            else:
                subprocess.Popen(["xdg-open", DATA_DIR])
        except Exception:
            self._show_error("无法打开数据目录：" + DATA_DIR)

    def _save_config(self):
        save_json(CONFIG_FILE, {
            "chrome_opacity": self.chrome_opacity,
            "geometry": self.root.geometry(),
            "theme": self._theme_name(),
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_bold": self.font_bold,
            "topmost": self.topmost,
            "list_slots": self.list_slots,
        }, backup=False)

    def _schedule_save(self):
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(400, self._save_config)

    # ========== 底板交互 ==========
    def _current_tags(self):
        cur = self.chrome.find_withtag("current")
        return self.chrome.gettags(cur[0]) if cur else ()

    def _chrome_motion(self, e):
        tags = self._current_tags()
        if any(t.startswith("btn_") for t in tags):
            cursor = "hand2"
        elif "grip" in tags:
            cursor = CURSOR_NWSE
        else:
            mode = self._edge_mode(e)
            cursor = {"r": CURSOR_WE, "b": CURSOR_NS,
                      "br": CURSOR_NWSE}.get(mode, "")
        if cursor != self._last_cursor:
            self._last_cursor = cursor
            self.chrome.config(cursor=cursor)

    def _chrome_press(self, e):
        tags = self._current_tags()
        if any(t.startswith("btn_") for t in tags):
            return
        if "grip" in tags:
            self._start_resize(e, "br")
            return
        if e.y <= HEADER_H:
            self._dragging = True
            self._dx = e.x_root - self.root.winfo_x()
            self._dy = e.y_root - self.root.winfo_y()
            return
        mode = self._edge_mode(e)
        if mode:
            self._start_resize(e, mode)

    def _chrome_drag(self, e):
        if self._resize_mode:
            self._do_resize(e)
        elif self._dragging:
            self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _chrome_release(self, _e):
        self._dragging = False
        self._resize_mode = None

    def _chrome_dblclick(self, e):
        tags = self._current_tags()
        if e.y <= HEADER_H and not any(t.startswith("btn_") for t in tags):
            self._toggle_collapse()

    # ========== 贴边缩放 ==========
    def _in_main_window(self, e):
        try:
            return e.widget.winfo_toplevel() is self.root
        except Exception:
            return False

    def _edge_mode(self, e):
        x = e.x_root - self.root.winfo_rootx()
        y = e.y_root - self.root.winfo_rooty()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if x < 0 or y < 0 or x > w or y > h:
            return None
        near_r = x >= w - EDGE
        near_b = y >= h - EDGE
        if near_r and near_b:
            return "br"
        if near_r:
            return "r"
        if near_b:
            return "b"
        return None

    def _cursor_update(self, e):
        if e.widget is self.chrome or not self._in_main_window(e):
            return
        if e.widget.winfo_class() in ("Entry", "Scale", "Scrollbar", "Text",
                                      "Spinbox", "TCombobox"):
            return
        mode = self._edge_mode(e)
        cursor = ({"r": CURSOR_WE, "b": CURSOR_NS, "br": CURSOR_NWSE}[mode]
                  if mode else
                  ("hand2" if getattr(e.widget, "_is_clickable", False) else ""))
        key = (e.widget, cursor)
        if key == self._last_cursor:
            return
        self._last_cursor = key
        try:
            e.widget.config(cursor=cursor)
        except Exception:
            pass

    def _edge_press(self, e):
        if e.widget is self.chrome or not self._in_main_window(e):
            return
        if getattr(e.widget, "_is_clickable", False):
            return
        if e.widget.winfo_class() in ("Entry", "Scale", "Scrollbar", "Text",
                                      "Spinbox", "TCombobox"):
            return
        mode = self._edge_mode(e)
        if mode:
            self._start_resize(e, mode)

    def _start_resize(self, e, mode):
        self._resize_mode = mode
        self._rx, self._ry = e.x_root, e.y_root
        self._rw = self.root.winfo_width()
        self._rh = self.root.winfo_height()

    def _edge_drag(self, e):
        if self._resize_mode and not self._dragging:
            self._do_resize(e)

    def _do_resize(self, e):
        dx, dy = e.x_root - self._rx, e.y_root - self._ry
        w, h = self._rw, self._rh
        if "r" in self._resize_mode:
            w = max(MIN_W, self._rw + dx)
        if "b" in self._resize_mode:
            if self._collapsed:
                h = HEADER_H + 1
            else:
                # 纵向缩放以栏位为单位吸附：每次增减都是完整的待办栏
                avail = self._rh + dy - HEADER_H - 8 - 26
                slots = int(round((avail + 8) / self._slot_h()))
                if len(self.todos) < 4:
                    slots = 3  # 少于 4 条待办时高度固定为 3 栏
                slots = min(max(slots, 3), 10)
                self.list_slots = slots
                h = self._height_for_slots(slots)
        self.root.geometry(f"{w}x{h}")
        # 每帧强制同步布局：内容紧跟窗口，消除空白闪烁
        self.root.update_idletasks()
        self._schedule_save()

    def _edge_release(self, _e):
        self._resize_mode = None

    # ========== 退出 ==========
    def _quit(self):
        self._cancel_jobs()
        self._save_config()
        save_json(DATA_FILE, self.todos)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TodoApp().run()
