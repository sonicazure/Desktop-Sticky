# -*- coding: utf-8 -*-
"""桌面防埋守卫（仅 Windows）：非置顶模式下，检测窗口是否被
「显示桌面」（Win+D / 任务栏右下角）抬起的桌面图层压盖；
若是则用「置顶弹跳」把窗口重新浮回桌面之上。

原理（Win11 实测结论）：
- Win+D 不会最小化无边框工具窗口，而是把 Progman/WorkerW 桌面层抬到
  普通窗口层最顶，把组件压在下面 —— 窗口 API 仍报告“可见/未最小化”，
  但屏幕上完全看不到（IsIconic/IsWindowVisible/DWM Cloak 均无异常，
  只有 WindowFromPoint 能发现中心点已被桌面窗口占据）；
- SetWindowPos(HWND_TOPMOST) 可以让窗口立即浮到桌面层之上，
  但【保持】置顶会在桌面还原后盖住应用窗口；
- 紧跟一次 HWND_NOTOPMOST（弹跳）：窗口落在普通窗口层最顶、
  桌面层之上；之后还原或新建的应用窗口仍排在它上方 ——
  既不消失，也不遮挡应用，无需常驻置顶。
"""
import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform.startswith("win")

if IS_WIN:
    _u = ctypes.windll.user32
    # 必须显式声明签名：默认 int 转换会把 (HWND)-1 截断成 0xFFFFFFFF，
    # 导致 SetWindowPos 静默失败（实测返回 0，窗口层级纹丝不动）
    _u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _u.SetWindowPos.restype = wintypes.BOOL

_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
_GA_ROOT = 2
_DESKTOP_CLASSES = ("Progman", "WorkerW")
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2


class DesktopGuard:
    """轮询式守卫：仅在用户关闭「窗口置顶」时启用。"""

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
            return 0

    def _buried(self):
        """窗口中心点被桌面层（Progman/WorkerW）压盖 -> True。"""
        h = self._hwnd()
        if not h:
            return False
        r = wintypes.RECT()
        if not _u.GetWindowRect(h, ctypes.byref(r)):
            return False
        pt = wintypes.POINT(int((r.left + r.right) / 2),
                            int((r.top + r.bottom) / 2))
        top = _u.WindowFromPoint(pt)
        if not top:
            return False
        top_root = _u.GetAncestor(top, _GA_ROOT)
        if not top_root or top_root == h:
            return False
        buf = ctypes.create_unicode_buffer(64)
        _u.GetClassNameW(top_root, buf, 64)
        return buf.value in _DESKTOP_CLASSES

    def _bounce(self):
        """置顶弹跳：TOPMOST -> NOTOPMOST，浮出桌面层后落回普通层最顶。"""
        h = self._hwnd()
        if not h:
            return
        _u.SetWindowPos(h, wintypes.HWND(_HWND_TOPMOST), 0, 0, 0, 0,
                        _SWP_FLAGS)
        _u.SetWindowPos(h, wintypes.HWND(_HWND_NOTOPMOST), 0, 0, 0, 0,
                        _SWP_FLAGS)

    def _poll(self):
        self._job = None
        try:
            if self._buried():
                self._bounce()
        except Exception:
            pass
        try:
            self._job = self.app.root.after(self.interval, self._poll)
        except Exception:
            pass  # 窗口已销毁
