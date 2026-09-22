# -*- coding: utf-8 -*-
"""桌面层级守卫（仅 Windows）：不置顶（置底）模式下维持
「桌面之上、应用窗口之下」的精确层级。

原理：
- 置底不是 SetWindowPos(HWND_BOTTOM) 一刀切——它可能把窗口压到
  桌面层（Progman/WorkerW）之下导致不可见，层级语义也不精确。
  正确做法是找到桌面图标层所在窗口（Progman，或 Win+D / 壁纸引擎时
  承载 SHELLDLL_DefView 的 WorkerW），把组件插到它的【正上方】：
  桌面层之上、所有普通窗口之下。
- Win+D「显示桌面」会把桌面层抬到普通窗口层最顶，把组件压在下面；
  轮询发现中心点被桌面层占据时，把组件重新插回该桌面层正上方——
  只浮出桌面、绝不越过任何应用窗口（旧的 TOPMOST→NOTOPMOST 弹跳
  会把组件抬到普通层最顶，一旦桌面层状态瞬时误判，组件就跳到其他
  窗口上面遮挡内容，且无法自行回落——层级乱跳的根因）。
- 桌面还原后桌面层自己掉回最底，组件自然落回「桌面之上、应用之下」，
  无需额外修正。
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
    _u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u.FindWindowW.restype = wintypes.HWND
    _u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                 wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u.FindWindowExW.restype = wintypes.HWND

_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
_GA_ROOT = 2
_DESKTOP_CLASSES = ("Progman", "WorkerW")
_HWND_BOTTOM = 1


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

    def _surface_over(self, desk_hwnd):
        """浮出桌面：插到压盖组件的桌面层正上方。
        只越过桌面层，不会抬到任何应用窗口之上；桌面还原后
        桌面层掉回最底，组件随之落回「桌面之上、应用之下」。"""
        h = self._hwnd()
        if not h or not desk_hwnd:
            return
        _u.SetWindowPos(h, wintypes.HWND(desk_hwnd), 0, 0, 0, 0,
                        _SWP_FLAGS)

    def _poll(self):
        self._job = None
        try:
            desk = self._covering_desktop()
            if desk:
                self._surface_over(desk)
        except Exception:
            pass
        try:
            self._job = self.app.root.after(self.interval, self._poll)
        except Exception:
            pass  # 窗口已销毁
