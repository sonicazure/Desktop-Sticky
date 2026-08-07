# -*- coding: utf-8 -*-
"""弹窗：新建待办、设置窗口、字体选择下拉。均为独立静态弹窗，风格统一。"""
import tkinter as tk

from .autostart import get_autostart
from .constants import HEADER_H, SIZE_CHOICES, THEMES
from .utils import clickable, ink_dy
from .widgets import Slider, Switch


# ---------- 新建待办弹窗 ----------
def open_add_dialog(app):
    if app._add_win:
        try:
            if app._add_win.winfo_exists():
                app._add_win.lift()
                app._add_win.focus_force()
                return
        except Exception:
            pass
        app._add_win = None
    if app._collapsed:
        app._toggle_collapse()
    th = app.theme
    win = tk.Toplevel(app.root)
    app._add_win = win
    win.withdraw()  # 先隐藏，定位后再显示，杜绝闪位
    win.title("新建待办")
    win.resizable(False, False)
    win.configure(bg=th["border"])
    win.transient(app.root)
    if app.topmost:
        win.attributes("-topmost", True)
    body = tk.Frame(win, bg=th["panel"], highlightthickness=0, bd=0)
    body.pack(padx=1, pady=1)
    inner = tk.Frame(body, bg=th["panel"])
    inner.pack(padx=16, pady=14)
    tk.Label(inner, text="新建待办", bg=th["panel"], fg=th["accent"],
             font=(app.group_font, app.font_size, "bold")).pack(
        anchor="w")
    entry = tk.Entry(inner, width=30, relief="flat", bd=0,
                     bg=th["hover"], fg=th["fg"],
                     insertbackground=th["fg"],
                     font=(app.font_family, app.font_size + 1))
    entry.pack(fill="x", ipady=7, pady=(8, 4))
    tk.Label(inner, text="回车添加 · Esc 取消", bg=th["panel"],
             fg=th["sub"], font=(app.font_family, app.font_size)).pack(
        anchor="w")

    def commit(_e=None):
        text = entry.get().strip()
        if text:
            app._add_todo_text(text)
        close()

    def close(_e=None):
        try:
            if win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        app._add_win = None

    entry.bind("<Return>", commit)
    entry.bind("<Escape>", close)
    win.bind("<FocusOut>", lambda e: win.after(
        150, lambda: close_add_if_unfocused(app, win)))
    win.protocol("WM_DELETE_WINDOW", close)
    # 定位：标题栏正下方、右对齐组件（加号键脚下）
    win.update_idletasks()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    x = app.root.winfo_x() + app.root.winfo_width() - ww
    y = app.root.winfo_y() + HEADER_H + 8
    x = min(max(0, x), win.winfo_screenwidth() - ww - 8)
    y = min(max(0, y), win.winfo_screenheight() - wh - 8)
    win.geometry(f"{ww}x{wh}+{x}+{y}")
    win.deiconify()
    win.lift(app.root)
    entry.focus_set()
    win.after(60, lambda: win.winfo_exists() and entry.focus_force())


def close_add_if_unfocused(app, win):
    try:
        if win.winfo_exists() and win.focus_get() is None:
            win.destroy()
            if app._add_win is win:
                app._add_win = None
    except Exception:
        pass


# ---------- 设置弹窗 ----------
def open_settings(app):
    if app.settings_win and app.settings_win.winfo_exists():
        app.settings_win.lift()
        return
    th = app.theme
    win = tk.Toplevel(app.root)
    app.settings_win = win
    win.withdraw()  # 先隐藏：构建+定位完成后才显示，窗口永不闪现在错误位置
    win.title("设置")
    win.resizable(False, False)
    win.configure(bg=th["panel"])
    win.transient(app.root)
    if app.topmost:
        win.attributes("-topmost", True)
    body = tk.Frame(win, bg=th["panel"])
    body.pack(padx=26, pady=(8, 14))

    # 左侧标签列：按最长标签的实际像素宽度取值（不用字符单位——
    # 字符单位随字体不同忽大忽小，是宽度失控的根源）
    label_px = app.font(app.font_family, app.font_size).measure(
        "开机自启") + 8
    line_h = app.font(app.font_family, app.font_size).metrics("linespace")
    sw_dy = ink_dy(app.font_size)  # 绘制类控件下偏量，对齐文字油墨中线
    # 定宽标签列的显式高度：取 pill 行高（linespace+10，全档位实测
    # 恒定），让所有行严格等高。propagate(False) 的框架若不显式
    # 给高度，reqheight≈0，switch 行会塌缩成 30px 两行挤在一起
    row_h = line_h + 10

    def group(title):
        tk.Label(body, text=title, bg=th["panel"], fg=th["accent"],
                 font=(app.group_font, app.font_size, "bold")).pack(
            anchor="w", pady=(12, 2))

    def row(label):
        f = tk.Frame(body, bg=th["panel"])
        f.pack(fill="x", pady=7)
        lc = tk.Frame(f, bg=th["panel"], width=label_px, height=row_h)
        lc.pack_propagate(False)
        lc.pack(side="left")
        tk.Label(lc, text=label, bg=th["panel"], fg=th["fg"],
                 font=(app.font_family, app.font_size),
                 anchor="w").pack(side="left", fill="x")
        rc = tk.Frame(f, bg=th["panel"])
        rc.pack(side="right", fill="x", expand=True)
        return f, rc

    def pill(parent, text, selected, cmd, side="right"):
        bg = th["accent"] if selected else th["hover"]
        fg = "#FFFFFF" if selected else th["fg"]
        p = tk.Label(parent, text=text, bg=bg, fg=fg,
                     font=(app.font_family, app.font_size),
                     padx=6, pady=3)
        clickable(p)
        p.pack(side=side, padx=2)
        p.bind("<Button-1>", lambda e: cmd())
        return p

    group("外观")

    r, rc = row("透明度")
    # 百分比右对齐贴边，与所有灰框/开关的右缘齐平
    pct_label = tk.Label(rc, text=f"{app.chrome_opacity}%",
                         bg=th["panel"], fg=th["fg"], width=4, anchor="e",
                         font=(app.font_family, app.font_size))
    pct_label.pack(side="right")
    # 自绘扁平滑杆：与 Switch 同一设计语言，图形下偏 sw_dy 对齐文字油墨
    scale = Slider(
        rc, from_=0, to=100, value=app.chrome_opacity, length=190,
        accent=th["accent"], trough=th["sub"], bg=th["panel"], dy=sw_dy,
        command=lambda v: app._set_chrome(v, pct_label, drag=True),
        release=lambda v: app._set_chrome(v, pct_label, drag=False))
    scale.pack(side="right", padx=(8, 4))
    r, rc = row("主题")
    for name in THEMES:
        pill(rc, name, name == app._theme_name(),
             lambda n=name: app._set_theme(n), side="right")

    r, rc = row("字体")
    # 字体选择按钮靠右，与所有灰框/开关右缘齐平
    font_btn = tk.Label(rc, text=app.font_family + " ▾",
                        bg=th["hover"], fg=th["fg"], padx=10, pady=3,
                        font=(app.font_family, app.font_size))
    clickable(font_btn)
    font_btn.pack(side="right", padx=(0, 2))
    font_btn.bind("<Button-1>",
                  lambda e: app._open_font_picker(font_btn))

    r, rc = row("字号")
    # 统一标准正方形按钮（边长 = 行高 row_h），靠右排列，
    # 逆序 pack 保持 9→14 从左到右，右缘与其他控件齐平
    for s in reversed(SIZE_CHOICES):
        selected = s == app.font_size
        sq_bg = th["accent"] if selected else th["hover"]
        sq_fg = "#FFFFFF" if selected else th["fg"]
        box = tk.Frame(rc, width=row_h, height=row_h, bg=sq_bg)
        box.pack_propagate(False)
        box.pack(side="right", padx=2)
        p = tk.Label(box, text=str(s), bg=sq_bg, fg=sq_fg,
                     font=(app.font_family, app.font_size))
        p.pack(expand=True)
        clickable(box)
        clickable(p)
        box.bind("<Button-1>", lambda e, v=s: app._set_font(None, v, None))
        p.bind("<Button-1>", lambda e, v=s: app._set_font(None, v, None))

    # 加粗放在字号下面：字体/字号两行相连，三个 Switch 全部右对齐
    r, rc = row("加粗")
    Switch(rc, on=app.font_bold, command=app._apply_bold,
           accent=th["accent"], bg=th["panel"]).pack(side="right",
                                                     pady=(sw_dy, 0))

    group("高级")
    r, rc = row("窗口置顶")
    Switch(rc, on=app.topmost, command=app._apply_topmost,
           accent=th["accent"], bg=th["panel"]).pack(side="right",
                                                     pady=(sw_dy, 0))
    r, rc = row("开机自启")
    Switch(rc, on=get_autostart(), command=app._apply_autostart,
           accent=th["accent"], bg=th["panel"]).pack(side="right",
                                                     pady=(sw_dy, 0))
    r, rc = row("清理")
    app.clear_btn = tk.Label(rc, text="清除已完成事项", bg=th["panel"],
                             fg=th["accent"],
                             font=(app.font_family, app.font_size),
                             padx=6, pady=2)
    clickable(app.clear_btn)
    app.clear_btn.pack(side="right")
    app.clear_btn.bind("<Button-1>", app._clear_done_click)
    r, rc = row("数据目录")
    open_btn = tk.Label(rc, text="打开数据文件夹", bg=th["panel"],
                        fg=th["accent"],
                        font=(app.font_family, app.font_size),
                        padx=6, pady=2)
    clickable(open_btn)
    open_btn.pack(side="right")
    open_btn.bind("<Button-1>", lambda e: app._open_data_dir())

    # 定位（窗口仍处于隐藏状态）：设置键附近——标题栏正下方、右对齐
    win.update_idletasks()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    x = app.root.winfo_x() + app.root.winfo_width() - ww
    y = app.root.winfo_y() + HEADER_H + 8
    x = min(max(0, x), win.winfo_screenwidth() - ww - 8)
    y = min(max(0, y), win.winfo_screenheight() - wh - 8)
    win.geometry(f"{ww}x{wh}+{x}+{y}")
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.bind("<Escape>", lambda e: win.destroy())
    # 一步到位显示在最终位置，并获得焦点（标题栏激活态）
    win.deiconify()
    win.lift(app.root)
    win.focus_set()
    win.after(60, lambda: win.winfo_exists() and win.focus_force())


def open_font_picker(app, anchor):
    """全主题化字体下拉：背景/文字/选中色全部显式指定，杜绝主题切换后看不清。"""
    if app._font_picker:
        try:
            if app._font_picker.winfo_exists():
                app._font_picker.destroy()
                app._font_picker = None
                return
        except Exception:
            pass
        app._font_picker = None
    th = app.theme
    win = tk.Toplevel(app.root)
    app._font_picker = win
    win.overrideredirect(True)
    win.configure(bg=th["border"])
    if app.topmost:
        win.attributes("-topmost", True)
    body = tk.Frame(win, bg=th["panel"], highlightthickness=0, bd=0)
    body.pack(padx=1, pady=1)
    sb = tk.Scrollbar(body, orient="vertical", bg=th["hover"],
                      troughcolor=th["panel"], bd=0,
                      highlightthickness=0, width=10,
                      activebackground=th["accent"])
    lb = tk.Listbox(
        body, height=12, width=22,
        font=(app.font_family, app.font_size),
        bg=th["panel"], fg=th["fg"],
        selectbackground=th["accent"], selectforeground="#FFFFFF",
        relief="flat", highlightthickness=0, bd=0,
        activestyle="none", exportselection=False,
        yscrollcommand=sb.set)
    sb.config(command=lb.yview)
    for f in app.font_families:
        lb.insert("end", f)
    try:
        idx = app.font_families.index(app.font_family)
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
        app._font_picker = None
        app._set_font(fam, None, None)

    lb.bind("<ButtonRelease-1>", pick)
    lb.bind("<Return>", pick)
    lb.bind("<Escape>", lambda e: win.destroy())
    win.bind("<FocusOut>", lambda e: win.after(
        150, lambda: close_picker_if_unfocused(app, win)))
    win.update_idletasks()
    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty() + anchor.winfo_height() + 4
    x = min(max(0, x), win.winfo_screenwidth() - win.winfo_width() - 8)
    y = min(max(0, y), win.winfo_screenheight() - win.winfo_height() - 8)
    win.geometry(f"+{x}+{y}")
    lb.focus_set()


def close_picker_if_unfocused(app, win):
    try:
        if win.winfo_exists() and win.focus_get() is None:
            win.destroy()
            if app._font_picker is win:
                app._font_picker = None
    except Exception:
        pass


def close_settings(app):
    if app._font_picker:
        try:
            if app._font_picker.winfo_exists():
                app._font_picker.destroy()
        except Exception:
            pass
        app._font_picker = None
    if app.settings_win and app.settings_win.winfo_exists():
        app.settings_win.destroy()
    app.settings_win = None
