# -*- coding: utf-8 -*-
"""桌面层级守卫（仅 Windows）：不置顶（置底）模式下维持
「桌面之上、应用窗口之下」的精确层级，并免疫 Win+D「显示桌面」。

原理：
- 置底不是 SetWindowPos(HWND_BOTTOM) 一刀切——它可能把窗口压到
  桌面层（Progman/WorkerW）之下导致不可见，层级语义也不精确。
  正确做法是找到桌面图标层所在窗口（Progman，或 Win+D / 壁纸引擎时
  承载 SHELLDLL_DefView 的 WorkerW），把组件插到它的【正上方】：
  桌面层之上、所有普通窗口之下。
- Win+D「显示桌面」会把桌面层抬到普通窗口层最顶。此时插在普通层
  任何位置都会被桌面层压盖（系统维持桌面层在普通层最上），唯一
  可靠的逃生通道是 TOPMOST 带——此刻应用窗口本就全部不可见，
  短暂置顶不算遮挡。
- 逃逸后进入「已逃逸」状态：轮询检测桌面层是否已落回（其上方
  不再有非置顶窗口 = 显示桌面结束），一旦结束就把组件重新插回
  桌面图标层正上方——落回「桌面之上、应用之下」，全程绝不会
  停留在应用窗口之上（旧的 TOPMOST→NOTOPMOST 弹跳会把组件留在
  普通层最顶遮挡其他窗口，是层级乱跳的根因）。
"""
import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform.startswith("win")

if IS_WIN:
    _u = ctypes.windll.user32
    # 必须显式声明签名：默认 int 转换会把 64 位 HWND 指针截断，
    # 导致 SetWindowPos / 句柄比较静默失败（实测返回 0，层级纹丝不动）
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _u.SetWindowPos.restype = wintypes.BOOL
    _u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _u.GetAncestor.restype = wintypes.HWND
    _u.WindowFromPoint.argtypes = [wintypes.POINT]
    _u.WindowFromPoint.restype = wintypes.HWND
    _u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _u.GetWindow.restype = wintypes.HWND
    _u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.GetWindowLongW.restype = ctypes.c_long
    _u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u.FindWindowW.restype = wintypes.HWND
    _u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                 wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u.FindWindowExW.restype = wintypes.HWND

_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
_GA_ROOT = 2
_DESKTOP_CLASSES = ("Progman", "WorkerW")
_HWND_TOPMOST = -1
_HWND_BOTTOM = 1
_GW_HWNDPREV = 3
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008


def _desktop_anchor():
    """桌面图标层所在窗口的 hwnd：Progman，或承载 SHELLDLL_DefView 的
    WorkerW（Win+D / 壁纸软件会把桌面图标挪进某个 WorkerW）。
    把组件插到它正上方 = 桌面之上、应用窗口之下。找不到返回 None。"""
    try:
        anchor = _u.FindWindowW("Progman", None)
        worker = None
        while True:
            worker = _u.FindWindowExW(None, worker, "WorkerW", None)
            if not worker:
                break
            if _u.FindWindowExW(worker, None, "SHELLDLL_DefView", None):
                anchor = worker  # 桌面图标层在这个 WorkerW 里
        return anchor or None
    except Exception:
        return None


def _desktop_raised():
    """桌面层是否被抬到普通窗口层最顶（即正处于「显示桌面」状态）。

    判定：桌面图标层上方的窗口若全是置顶带窗口（或没有窗口），
    说明桌面层已占据普通层最顶；只要上方存在一个非置顶窗口，
    桌面层就还在普通层底部（正常状态）。
    """
    try:
        anchor = _desktop_anchor()
        if not anchor:
            return False
        above = _u.GetWindow(anchor, _GW_HWNDPREV)
        while above:
            ex = _u.GetWindowLongW(above, _GWL_EXSTYLE)
            if not (ex & _WS_EX_TOPMOST):
                return False  # 桌面层上方有普通窗口：未被抬起
            above = _u.GetWindow(above, _GW_HWNDPREV)
        return True
    except Exception:
        return False


def pin_to_bottom(tk_widget):
    """置底：把窗口插到桌面图标层正上方（桌面之上、所有普通窗口之下）。

    NOACTIVATE 不抢焦点，立即生效，之后打开的窗口天然压在它上方。
    找不到桌面层时退化为 HWND_BOTTOM。非 Windows 平台静默返回 False。
    """
    if not IS_WIN:
        return False
    try:
        h = _u.GetAncestor(tk_widget.winfo_id(), _GA_ROOT)
        if not h:
            return False
        anchor = _desktop_anchor()
        insert_after = wintypes.HWND(anchor) if anchor \
            else wintypes.HWND(_HWND_BOTTOM)
        return bool(_u.SetWindowPos(h, insert_after, 0, 0, 0, 0,
                                    _SWP_FLAGS))
    except Exception:
        return False


class DesktopGuard:
    """轮询式守卫：仅在「不置顶（置底）」模式启用。"""

    def __init__(self, app, interval=400):
        self.app = app
        self.interval = interval
        self._job = None
        self._escaped = False  # 已用 TOPMOST 逃出「显示桌面」压盖，等待落回

    # ---------- 生命周期 ----------
    def start(self):
        if not IS_WIN or self._job is not None:
            return
        self._poll()

    def stop(self):
        if self._job is not None:
            try:
                self.app.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    # ---------- 内部 ----------
    def _hwnd(self):
        try:
            return _u.GetAncestor(self.app.root.winfo_id(), _GA_ROOT)
        except Exception:
            return None

    def _covering_desktop(self):
        """压住组件中心点的桌面层 hwnd；未被桌面层压盖返回 None。"""
        h = self._hwnd()
        if not h:
            return None
        r = wintypes.RECT()
        if not _u.GetWindowRect(h, ctypes.byref(r)):
            return None
        pt = wintypes.POINT(int((r.left + r.right) / 2),
                            int((r.top + r.bottom) / 2))
        top = _u.WindowFromPoint(pt)
        if not top:
            return None
        top_root = _u.GetAncestor(top, _GA_ROOT)
        if not top_root or top_root == h:
            return None
        buf = ctypes.create_unicode_buffer(64)
        _u.GetClassNameW(top_root, buf, 64)
        return top_root if buf.value in _DESKTOP_CLASSES else None

    def _escape(self):
        """逃出桌面层压盖：抬入 TOPMOST 带（显示桌面期间应用窗口本就
        不可见，短暂置顶不算遮挡）。不用 NOTOPMOST 落回——那会把组件
        留在普通层最顶，遮挡之后显示的窗口。"""
        h = self._hwnd()
        if not h:
            return
        _u.SetWindowPos(h, wintypes.HWND(_HWND_TOPMOST), 0, 0, 0, 0,
                        _SWP_FLAGS)
        self._escaped = True

    def _poll(self):
        self._job = None
        try:
            if self._escaped:
                # 显示桌面结束（桌面层落回）后，立刻落回置底位置
                if not _desktop_raised():
                    self._escaped = False
                    pin_to_bottom(self.app.root)
            elif self._covering_desktop():
                self._escape()
        except Exception:
            pass
        try:
            self._job = self.app.root.after(self.interval, self._poll)
        except Exception:
            pass  # 窗口已销毁
