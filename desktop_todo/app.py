# -*- coding: utf-8 -*-
"""主程序：无边框桌面待办小组件。

- 标题栏拖动移动，右 / 下 / 右下角贴边缩放（拖拽时每帧同步布局）
- 透明度 0–100% 滑杆（有序抖动点阵）：底板与卡片底色淡出，文字实心
- 双主题、行内编辑、删除/清除可撤销、双击标题栏折叠
"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont

from . import dialogs, dockguard, storage
from .autostart import entry_script, get_autostart_value, set_autostart
from .constants import (_BAYER8, CURSOR_NS, CURSOR_NWSE, CURSOR_WE, EDGE,
                        HEADER_H, KEY, MIN_H, MIN_W, SIZE_CHOICES, THEMES,
                        TITLE_FONT)
from .todo_item import TodoItem
from .utils import clickable, enable_dpi_awareness


class TodoApp:
    def __init__(self):
        enable_dpi_awareness()

        self.config = storage.load_json(storage.CONFIG_FILE, {})
        self.todos = storage.load_json(storage.DATA_FILE, [])
        self._next_id = max([t.get("id", 0) for t in self.todos], default=0) + 1
        self.item_widgets = {}
        self._item_wins = {}
        self._item_top = {}
        self._resize_mode = None
        self._dragging = False
        self._save_after = None
        self._restack_job = None
        self._heal_job = None
        self._warmup_job = None
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
        self._chrome_after = None
        self._painting = False

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
        # 冷启动预热：界面落定后趁空闲把首交互路径预演一遍（详见 _warmup）
        self._warmup_job = self.root.after(350, self._warmup)

        # 桌面防埋守卫：仅在非置顶时轮询，防止 Win+D「显示桌面」后
        # 组件被桌面图层压盖且无法找回（置顶模式下系统本就免疫）
        self._guard = dockguard.DesktopGuard(self)
        if not self.topmost:
            self._guard.start()

    # ========== 工具 ==========
    def lerp(self, c1, c2, t):
        a = self.root.winfo_rgb(c1)
        b = self.root.winfo_rgb(c2)
        return "#%02x%02x%02x" % tuple(
            int((a[i] + (b[i] - a[i]) * t) / 256) for i in range(3))

    def _cancel_jobs(self):
        for attr in ("_restack_job", "_save_after", "_undo_after",
                     "_error_after", "_heal_job", "_warmup_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _on_destroy(self, e):
        if e.widget is self.root:
            if self._guard:
                self._guard.stop()
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
            d = os.path.join(storage.DATA_DIR, "stipples")
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

    # ========== 冷启动预热 ==========
    def _warmup(self):
        """空闲预热：把首几次点击/拖动的“首次”开销提前到启动后空闲时完成。

        首几次交互动画卡顿的根因是一串惰性初始化全堆在第一次操作上：
        - 删除线字体 / 删除键字体的首次创建（GDI 字体加载）
        - XBM 点阵位图的首次磁盘读取与 Tcl 位图注册
        - 内嵌子窗口 / Entry 控件类的首次 HWND 创建（Windows 上最贵）
        - 首次原子写盘（杀软对 .tmp 替换的首次扫描）
        在一个屏外探针画布上各预演一次即可，之后交互全部命中热缓存。
        """
        self._warmup_job = None
        try:
            w = "bold" if self.font_bold else "normal"
            f_norm = self.font(self.font_family, self.font_size, w)
            f_done = self.font(self.font_family, self.font_size, w,
                               overstrike=True)
            f_del = (self.font_family, self.font_size + 2)
            probe = tk.Canvas(self.root, bg=KEY, highlightthickness=0,
                              bd=0, width=8, height=8)
            probe.place(x=-5000, y=-5000)  # 屏外探针，永不可见
            # 点阵位图：item 配置 stipple 时即载入 Tcl 位图缓存
            for pct in (16, 72, self.chrome_opacity):
                rid = probe.create_rectangle(
                    0, 0, 8, 8, fill=self.theme["item"],
                    stipple=self._stipple_for(pct))
                probe.delete(rid)
            # 文本渲染路径：普通 / 删除线 / 删除键字体各画一次
            probe.create_text(0, 0, text="Aa 预", font=f_norm)
            probe.create_text(0, 0, text="Aa 预", font=f_done)
            probe.create_text(0, 0, text="✕", font=f_del)
            # 内嵌子窗口创建/销毁（勾选置顶重建、拖拽替身共用此路径）
            child = tk.Canvas(probe, bg=KEY, highlightthickness=0, bd=0,
                              width=4, height=4)
            cwin = probe.create_window(0, 0, window=child, anchor="nw")
            # Entry 控件类（行内编辑首次弹出）
            ent = tk.Entry(probe, font=f_norm)
            ewin = probe.create_window(0, 0, window=ent, anchor="nw")
            self.root.update_idletasks()
            probe.delete(ewin)
            ent.destroy()
            probe.delete(cwin)
            child.destroy()
            probe.destroy()
            # 首次磁盘原子写入路径（内容不变，等价于一次普通保存）
            storage.save_json(storage.DATA_FILE, self.todos)
        except Exception:
            pass
        self._warmup_tick()

    def _warmup_tick(self, i=0):
        """空转几拍 15ms 定时器：与滑动动画 _glide_win 同款的 after 链，
        预热 Tcl 定时器，避免首个动画帧定时器惰性初始化造成起步卡顿。"""
        if i >= 6:
            return
        try:
            self.root.after(15, lambda: self._warmup_tick(i + 1))
        except Exception:
            pass

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

    def _apply_height(self, h):
        """设置窗口高度并同步布局（与 _do_resize 同路径）。"""
        w = self.root.winfo_width()
        self.root.geometry(f"{w}x{h}")
        self._layout(force=True, size=(w, h))
        self._flush_paints()

    def _flush_paints(self):
        """同帧完成绘制：先处理积压的 Configure 等事件（让各画布按新尺寸
        排布重绘任务），再触发重绘，保证本函数返回时画面已是最新。
        仅用 update_idletasks 不够：重绘任务要等事件队列里的 Configure
        被处理后才会注册，期间的帧就是破洞。用带防重入守卫的 update
        一次性处理完。"""
        if self._painting:
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            return
        self._painting = True
        try:
            self.root.update()
        except Exception:
            try:
                self.root.update_idletasks()
            except Exception:
                pass
        finally:
            self._painting = False

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
        self._painting = False
        self.item_widgets = {}
        self._item_wins = {}
        self._item_top = {}
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
        self.title_item = self.chrome.create_text(
            18, cy, text="To-Do List", anchor="w",
            font=TITLE_FONT, fill=th["header_fg"])
        for name in ("close", "settings", "plus"):
            self._make_icon(name)
        self.grip_item = self.chrome.create_text(
            0, 0, text="◢", anchor="se", fill=th["sub"],
            font=(self.font_family, 10), tags="grip")
        # 折叠提示：有待办被窗口下沿裁掉时，底部条带中央浮现一个小箭头。
        # 纯展示、不响应任何交互（无标签，事件按普通底板处理）
        self.hint_item = self.chrome.create_text(
            0, 0, text="▾", anchor="s", fill=th["sub"], state="hidden",
            font=(self.font_family, max(9, self.font_size - 1)))

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
            # 隐形热区：扩大可点击面积（方案一）
            items.append(self.chrome.create_oval(
                -18, -18, 18, 18, fill="", outline=""))
        elif name == "close":
            items.append(self.chrome.create_line(
                -s, -s, s, s, fill=color, width=2.6, capstyle="round"))
            items.append(self.chrome.create_line(
                -s, s, s, -s, fill=color, width=2.6, capstyle="round"))
            # 隐形热区：扩大可点击面积
            items.append(self.chrome.create_oval(
                -18, -18, 18, 18, fill="", outline=""))
        elif name == "settings":
            # 滑杆式设置图标：三条横线 + 错位旋钮，不会被误认为太阳
            for ly, kx in ((-8, -4), (0, 5), (8, -1)):
                items.append(self.chrome.create_line(
                    -9, ly, 9, ly, fill=color, width=2.2, capstyle="round"))
                items.append(self.chrome.create_oval(
                    kx - 3.4, ly - 3.4, kx + 3.4, ly + 3.4,
                    fill=color, outline=""))
            # 隐形热区：扩大可点击面积
            items.append(self.chrome.create_oval(
                -18, -18, 18, 18, fill="", outline=""))
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
                # 跳过隐形热区（fill=""），避免悬停后变成实心圆遮挡图标
                if self.chrome.itemcget(it, "fill") == "":
                    continue
                self.chrome.itemconfig(it, fill=color, outline=color)
            else:
                self.chrome.itemconfig(it, fill=color)

    def _move_icon(self, name, cx, cy):
        ox, oy = self._icon_cx.get(name, (0, 0))
        for it in self._icon_items.get(name, []):
            self.chrome.move(it, cx - ox, cy - oy)
        self._icon_cx[name] = (cx, cy)

    # ---------- 布局 ----------
    def _layout(self, _e=None, force=False, size=None):
        if size is not None:
            W, H = size  # 缩放拖拽时直接传入目标尺寸，绕过事件队列
        else:
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
            self._update_hint()
        else:
            self.chrome.itemconfig(self.grip_item, state="normal")
            self.chrome.coords(self.grip_item, W - 10, H - 8)
            list_y = HEADER_H + 8
            self.chrome.itemconfig(self.scroll_win, state="normal")
            self.chrome.coords(self.scroll_win, 14, list_y)
            list_w, list_h = W - 28, max(40, H - list_y - 26)
            self.chrome.itemconfig(self.scroll_win, width=list_w,
                                   height=list_h)
            self.chrome.coords(self.hint_item, W / 2, H - 3)
            # 列表内部同步跟随：不等列表画布自己的 <Configure> 事件
            self._sync_list(list_w, list_h)

    # ---------- 列表内部布局 ----------
    def _sync_list(self, w, h):
        """列表画布尺寸同步（宽高均为像素，可来自事件或显式目标尺寸）。
        背景与空状态即时跟随；宽度变化时卡片边框即时跟随（廉价），
        文字重排防抖。顺带刷新折叠提示。"""
        self.canvas.coords(self.list_bg, 0, 0, w, h)
        self._layout_empty()
        if w != self._last_cw:
            self._last_cw = w
            cw = max(120, w - 2)
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
        self._update_hint(vh=h)

    def _on_scroll_configure(self, e):
        self._sync_list(e.width, e.height)

    def _fire_restack(self):
        self._restack_job = None
        self._restack()

    def _restack(self):
        """重排卡片：设置文字宽度 -> 量高 -> 堆叠 -> 滚动区域。"""
        w = self.canvas.winfo_width()
        if w <= 1:
            # 画布尚未映射：定时重试直至拿到真实宽度。早期 restack
            # 在映射前空跑返回后，宽度去重会让补偿重排不再触发，
            # 卡片就此停留在未布局状态（文字按初始窄宽换行、
            # 删除键留在 (0,24)）——必须自愈重试
            if self._restack_job:
                self.root.after_cancel(self._restack_job)
            self._restack_job = self.root.after(60, self._fire_restack)
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
        self._item_top = {}
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
            self._item_top[tid] = y
            y += h + 8
        self.canvas.configure(scrollregion=(0, 0, w, max(y - 8, 1)))
        self._update_hint()

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
        text_item = c.create_text(item.text_left, h / 2, anchor="w",
                                  text=item.todo["text"],
                                  font=item.font_done if done else item.font_normal,
                                  fill=th["sub"] if done else th["fg"],
                                  width=w - item.text_left - item.DEL_RESERVE)
        # 勾选圈与真身 _draw_check 完全一致（含点阵填充与白色对勾），
        # 中线对齐文字油墨（bbox 中心 + ink_dy 下偏量）
        bbox = c.bbox(text_item)
        cy = (bbox[1] + bbox[3]) / 2 if bbox else h / 2
        s = item.check_size
        x0, y0 = item.LEFT, cy + item._ink_dy - s / 2
        ring_p = 2.2
        fill_p = ring_p + 2.4
        if done:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["sub"],
                          stipple=item._stip_dense, outline="")
            c.create_oval(x0 + ring_p, y0 + ring_p, x0 + s - ring_p,
                          y0 + s - ring_p, outline=th["sub"], width=2.2)
        else:
            c.create_oval(x0 + fill_p, y0 + fill_p, x0 + s - fill_p,
                          y0 + s - fill_p, fill=th["accent"],
                          stipple=item._stip_light, outline="")
            c.create_oval(x0 + ring_p, y0 + ring_p, x0 + s - ring_p,
                          y0 + s - ring_p, outline=th["accent"], width=2.0)
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
        纯坐标滑动，不重建任何控件——分层透明窗口下 HWND 销毁/创建
        会触发整窗重新合成，是动画起步卡顿与结束后闪烁的根因。"""
        w = self.canvas.winfo_width()
        if w <= 1:
            self.render_items()
            return
        order = self._ordered_ids()
        y = 0
        targets = {}
        for tid in order:
            item = self.item_widgets.get(tid)
            if not item:
                continue
            targets[tid] = y
            y += item.height + 8
        self._item_top.update(targets)  # 动画终点即最终堆叠位置
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
        self._update_hint()

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
            # 销毁替身（真身一直在屏外 -3000 处保留，完好无损）
            try:
                self.canvas.delete(dragged_win)
                r["proxy"].destroy()
            except Exception:
                pass
            # 写回顺序（seq 即视觉索引），保存并归位。
            # 用 _restack 而非 render_items：卡片控件零销毁零重建，
            # 避免松手瞬间整窗重建带来的闪烁与卡顿
            by_id = {t["id"]: t for t in self.todos}
            for i, t_id in enumerate(order):
                if t_id in by_id:
                    by_id[t_id]["seq"] = i
            self._save_todos()
            self._restack()

        if tid in final:
            self._glide_win(dragged_win, final[tid], ms=120, done=finish)
        else:
            finish()

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

    # ---------- 折叠提示（被窗口下沿裁掉的待办） ----------
    def _update_hint(self, vh=None):
        """有待办完全藏到可视区下沿之外时，底部条带中央显示一个小箭头。
        纯展示不交互。vh 可显式传入列表可视高度（缩放拖拽中 winfo
        尚未生效时用）。"""
        try:
            if self._collapsed or not self.todos:
                self.chrome.itemconfig(self.hint_item, state="hidden")
                return
            if vh is None:
                vh = self.canvas.winfo_height()
            if vh <= 1:
                return
            bottom = self.canvas.canvasy(vh)
            hidden = any(top >= bottom - 2
                         for top in self._item_top.values())
            self.chrome.itemconfig(self.hint_item,
                                   state="normal" if hidden else "hidden")
        except Exception:
            pass

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
        """以栏位为单位设置窗口高度（3~10 栏），同步布局同帧画实。"""
        slots = min(max(int(slots), 3), 10)
        self.list_slots = slots
        if not self._collapsed:
            h = self._height_for_slots(slots)
            if h != self.root.winfo_height():
                self._apply_height(h)
        if save:
            self._schedule_save()

    def _auto_slots(self):
        """待办数变化时：栏位自动跟随（3 起步，10 封顶）。"""
        self._set_slots(min(max(len(self.todos), 3), 10))

    # ---------- 新建待办 / 设置 / 折叠 ----------
    def _open_add_dialog(self):
        dialogs.open_add_dialog(self)

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
            self._apply_height(h)  # 展开拉高：同步布局同帧画实
        else:
            self._collapsed = True
            self.root.minsize(MIN_W, HEADER_H + 1)
            w = self.root.winfo_width()
            self.root.geometry(f"{w}x{HEADER_H + 1}")
            self._layout(force=True, size=(w, HEADER_H + 1))
        self._schedule_save()

    # ========== 设置弹窗（独立静态窗口，实现在 dialogs 模块） ==========
    def _open_settings(self):
        dialogs.open_settings(self)

    def _open_font_picker(self, anchor):
        dialogs.open_font_picker(self, anchor)

    def _close_settings(self):
        dialogs.close_settings(self)

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
            if t["id"] == self._flash_id:
                item.flash()
        self._flash_id = None
        self._restack()
        self._layout_empty()

    def _save_todos(self):
        if not storage.save_json(storage.DATA_FILE, self.todos):
            self._show_error("待办保存失败，请检查磁盘权限")

    def _add_todo_text(self, text):
        self.todos.append({"id": self._next_id, "text": text,
                           "done": False, "seq": self._next_id})
        self._flash_id = self._next_id
        self._next_id += 1
        self._save_todos()
        self.render_items()
        self.canvas.yview_moveto(0)  # 无滚轮交互：视图始终锚定顶部
        self.root.after_idle(self._update_hint)
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
    def _set_chrome(self, val, pct_label=None, drag=False):
        self.chrome_opacity = int(val)
        if pct_label is not None:
            pct_label.config(text=f"{self.chrome_opacity}%")
        # 拖动中防抖：避免每帧全量重绘，释放时立即刷新
        if self._chrome_after:
            try:
                self.root.after_cancel(self._chrome_after)
            except Exception:
                pass
            self._chrome_after = None
        if drag:
            self._chrome_after = self.root.after(50, self._apply_chrome)
        else:
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
        settings_pos = None
        if settings_open:
            try:
                settings_pos = (self.settings_win.winfo_x(),
                                self.settings_win.winfo_y())
            except Exception:
                pass
        self._build_ui()
        self._set_slots(self.list_slots, save=False)  # 字号变化后栏位重算
        if settings_open:
            self._close_settings()
            self._open_settings()  # 按新内容的 reqwidth/reqheight 重新定尺寸
            if settings_pos:
                # 只恢复【位置】，不恢复旧尺寸——旧尺寸是在旧字号下量出的，
                # 强行套用会把放大后的内容裁掉（左侧栏截断、数据目录行消失）
                try:
                    win = self.settings_win
                    win.update_idletasks()
                    x = min(max(0, settings_pos[0]),
                            win.winfo_screenwidth() - win.winfo_width() - 8)
                    y = min(max(0, settings_pos[1]),
                            win.winfo_screenheight() - win.winfo_height() - 8)
                    win.geometry(f"+{x}+{y}")
                except Exception:
                    pass

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
        if self._guard:
            if on:
                self._guard.stop()    # 置顶模式天然免疫 Win+D
            else:
                self._guard.start()   # 非置顶：轮询防埋
        self._save_config()

    def _apply_autostart(self, on):
        if not set_autostart(on):
            self._show_error("开机自启设置失败")

    def _heal_autostart(self):
        self._heal_job = None
        val = get_autostart_value()
        if val and entry_script().lower() not in val.lower():
            set_autostart(True)

    def _open_data_dir(self):
        try:
            if hasattr(os, "startfile"):
                os.startfile(storage.DATA_DIR)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", storage.DATA_DIR])
            else:
                subprocess.Popen(["xdg-open", storage.DATA_DIR])
        except Exception:
            self._show_error("无法打开数据目录：" + storage.DATA_DIR)

    def _save_config(self):
        storage.save_json(storage.CONFIG_FILE, {
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
        if (w, h) == self._last_layout_size:
            return  # 栏位吸附后尺寸未变：跳过冗余的窗口重设与合成
        self.root.geometry(f"{w}x{h}")
        # 同步布局（关键修复）：直接按目标尺寸重排画布元素并立即重绘，
        # 不等 <Configure> 事件绕事件队列一圈。否则拉伸时新露出的区域
        # 会先被系统按色键擦除——而色键是全透明的，表现为一串“内容消失”
        # 的破洞，下一帧才填回（拉伸闪烁的根因；缩短没有新增暴露区，
        # 所以一直很流畅）。
        self._layout(force=True, size=(w, h))
        self._flush_paints()
        self._schedule_save()

    def _edge_release(self, _e):
        self._resize_mode = None

    # ========== 退出 ==========
    def _quit(self):
        if self._guard:
            self._guard.stop()
        self._cancel_jobs()
        self._save_config()
        storage.save_json(storage.DATA_FILE, self.todos)
        self.root.destroy()

    def run(self):
        self.root.mainloop()
