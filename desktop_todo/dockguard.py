# -*- coding: utf-8 -*-
"""Click-driven Windows desktop layering; all Z-order changes belong here.

A dedicated mouse-hook thread records the real hit window before activation.
It never calls Tk. It consumes only a covered widget's activation click,
including the matching release. The Tk thread handles state and repairs
shell restacking without taking focus. Hovering never changes the layer.
"""
import ctypes
import logging
import queue
import sys
import threading
import time
from ctypes import wintypes as W

IS_WIN = sys.platform.startswith("win")
log = logging.getLogger(__name__)
FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
TOPMOST, NOTOPMOST, TOP = -1, -2, 0
ROOT, NEXT, PREV, OWNER = 2, 2, 3, 4
EXSTYLE, HWNDPARENT = -20, -8
TOOLWINDOW, APPWINDOW = 0x80, 0x40000
MOUSE_DOWN = {0x0201, 0x0204, 0x0207, 0x020B}
MOUSE_UP = {0x0202: 0x0201, 0x0205: 0x0204,
            0x0208: 0x0207, 0x020C: 0x020B}
EXCLUDED_FROM_PEEK, CLOAKED, FRAME_BOUNDS = 12, 14, 9

if IS_WIN:
    _u = ctypes.WinDLL("user32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwm = ctypes.WinDLL("dwmapi", use_last_error=True)

    def _declare(dll, name, result, *args):
        fn = getattr(dll, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn

    _declare(_u, "SetWindowPos", W.BOOL, W.HWND, W.HWND,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT)
    for name in ("GetAncestor", "GetWindow"):
        _declare(_u, name, W.HWND, W.HWND, W.UINT)
    _declare(_u, "GetTopWindow", W.HWND, W.HWND)
    _declare(_u, "GetShellWindow", W.HWND)
    _declare(_u, "GetForegroundWindow", W.HWND)
    _declare(_u, "WindowFromPoint", W.HWND, W.POINT)
    _declare(_u, "WindowFromPhysicalPoint", W.HWND, W.POINT)
    _declare(_u, "GetWindowRect", W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
    _declare(_u, "SetForegroundWindow", W.BOOL, W.HWND)
    for name in ("DwmSetWindowAttribute", "DwmGetWindowAttribute"):
        _declare(_dwm, name, ctypes.c_long, W.HWND, W.DWORD,
                 ctypes.c_void_p, W.DWORD)
    for name in ("IsWindow", "IsWindowVisible", "IsIconic"):
        _declare(_u, name, W.BOOL, W.HWND)
    _declare(_u, "ShowWindow", W.BOOL, W.HWND, ctypes.c_int)
    _declare(_u, "GetClassNameW", ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
    _declare(_u, "GetWindowThreadProcessId", W.DWORD, W.HWND,
             ctypes.POINTER(W.DWORD))
    _suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
    _get_long = _declare(_u, "GetWindowLong" + _suffix, ctypes.c_ssize_t,
                         W.HWND, ctypes.c_int)
    _set_long = _declare(_u, "SetWindowLong" + _suffix, ctypes.c_ssize_t,
                         W.HWND, ctypes.c_int, ctypes.c_ssize_t)
    _HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                  W.WPARAM, W.LPARAM)
    _declare(_u, "SetWindowsHookExW", W.HANDLE, ctypes.c_int, _HOOKPROC,
             W.HINSTANCE, W.DWORD)
    _declare(_u, "CallNextHookEx", ctypes.c_ssize_t, W.HANDLE,
             ctypes.c_int, W.WPARAM, W.LPARAM)
    _declare(_u, "UnhookWindowsHookEx", W.BOOL, W.HANDLE)
    _declare(_u, "GetMessageW", ctypes.c_int, ctypes.POINTER(W.MSG),
             W.HWND, W.UINT, W.UINT)
    _declare(_u, "PeekMessageW", W.BOOL, ctypes.POINTER(W.MSG),
             W.HWND, W.UINT, W.UINT, W.UINT)
    _declare(_u, "TranslateMessage", W.BOOL, ctypes.POINTER(W.MSG))
    _declare(_u, "DispatchMessageW", ctypes.c_ssize_t, ctypes.POINTER(W.MSG))
    _declare(_u, "PostThreadMessageW", W.BOOL, W.DWORD, W.UINT,
             W.WPARAM, W.LPARAM)
    _declare(_k, "GetCurrentThreadId", W.DWORD)
    _declare(_k, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
    _set_thread_dpi = None
    if hasattr(_u, "SetThreadDpiAwarenessContext"):
        _set_thread_dpi = _declare(_u, "SetThreadDpiAwarenessContext",
                                   W.HANDLE, W.HANDLE)

    class _MouseInfo(ctypes.Structure):
        _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD),
                    ("flags", W.DWORD), ("time", W.DWORD),
                    ("extra", ctypes.c_size_t)]


def _class_of(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    _u.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _windows():
    """Bound enumeration even if Explorer is reordering windows."""
    result, seen = [], set()
    hwnd = _u.GetTopWindow(None)
    while hwnd and hwnd not in seen:
        seen.add(hwnd)
        result.append(hwnd)
        hwnd = _u.GetWindow(hwnd, NEXT)
    return result


def _position(hwnd, after):
    if not _u.SetWindowPos(hwnd, after, 0, 0, 0, 0, FLAGS):
        raise ctypes.WinError(ctypes.get_last_error())


def _desktop_anchor(windows):
    shell = _u.GetShellWindow()
    if not shell:
        return None  # Explorer restart: never fall back below the wallpaper.
    pid = W.DWORD()
    _u.GetWindowThreadProcessId(shell, ctypes.byref(pid))
    for hwnd in windows:
        other = W.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(other))
        if (other.value == pid.value and _u.IsWindowVisible(hwnd)
                and _class_of(hwnd) in ("Progman", "WorkerW")):
            return hwnd
    return shell if shell in windows else None


def _insert_above(hwnd, anchor):
    # SetWindowPos inserts AFTER its argument, never above it.
    previous = _u.GetWindow(anchor, PREV)
    if previous == hwnd:
        return
    # Inserting after a topmost window would promote us. TOP avoids that.
    if previous and _get_long(previous, EXSTYLE) & 0x8:
        previous = TOP
    _position(hwnd, previous or TOP)


def _frame(hwnd):
    rect = W.RECT()
    # DWM bounds exclude invisible resize borders/shadows, unlike GetWindowRect.
    if _dwm.DwmGetWindowAttribute(hwnd, FRAME_BOUNDS, ctypes.byref(rect),
                                  ctypes.sizeof(rect)) != 0:
        if not _u.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    return rect


def _overlaps(a, b):
    return (a is not None and b is not None
            and max(a.left, b.left) < min(a.right, b.right)
            and max(a.top, b.top) < min(a.bottom, b.bottom))


def _covered(hwnd, own):
    """Inspect actual Z order before Windows activates the clicked window.

    Only visible, non-cloaked foreign windows with overlapping content bounds
    count. Mere inactivity or a window elsewhere on screen does not consume a
    click. A completely covered window cannot be clicked through another app.
    """
    rect = _frame(hwnd)
    for other in _windows():
        if other == hwnd:
            break
        if (other in own or not _u.IsWindowVisible(other)
                or _u.IsIconic(other)
                or _class_of(other) in ("Progman", "WorkerW")):
            continue
        cloaked = W.DWORD()
        _dwm.DwmGetWindowAttribute(other, CLOAKED, ctypes.byref(cloaked),
                                   ctypes.sizeof(cloaked))
        if not cloaked.value and _overlaps(rect, _frame(other)):
            return True
    return False


class _MouseWatcher:
    def __init__(self, events, targets=()):
        self.events = events
        self.targets = tuple(targets)  # Immutable snapshots from the Tk thread.
        self._eaten = set()
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.thread_id = None
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="Desktop click watcher")

    def _click(self, message, info):
        # Distinguish the two X buttons so a different release is not swallowed.
        button = (info.mouseData >> 16) if message in (0x020B, 0x020C) else 0
        key = (MOUSE_UP.get(message, message), button)
        if message in MOUSE_UP:
            if key in self._eaten:
                self._eaten.remove(key)
                return True
            return False
        hit = _u.WindowFromPhysicalPoint(info.pt)
        target = _u.GetAncestor(hit, ROOT) or hit
        eat = target in self.targets and _covered(target, self.targets)
        self.events.put((target, True) if eat else target)
        if eat:
            self._eaten.add(key)
        return eat

    def start(self):
        self.thread.start()
        if not self.ready.wait(2):
            self.stop()
            raise RuntimeError("Mouse watcher did not start")
        if self.error:
            raise self.error

    def _run(self):
        hook = None
        try:
            if _set_thread_dpi:
                _set_thread_dpi(-4)  # PER_MONITOR_AWARE_V2, physical coordinates
            self.thread_id = _k.GetCurrentThreadId()
            msg = W.MSG()
            _u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

            @_HOOKPROC
            def callback(code, message, data):
                if code >= 0 and (message in MOUSE_DOWN or message in MOUSE_UP):
                    info = ctypes.cast(data, ctypes.POINTER(_MouseInfo)).contents
                    # Hook coordinates are physical, even for DPI-unaware Tk
                    # threads; logical hit testing misidentifies scaled screens.
                    try:
                        if self._click(message, info):
                            return 1
                    except Exception:
                        log.exception("Could not inspect activation click")
                return _u.CallNextHookEx(None, code, message, data)

            hook = _u.SetWindowsHookExW(
                14, callback, _k.GetModuleHandleW(None), 0)
            if not hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self.ready.set()
            while not self.stopping.is_set():
                result = _u.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                _u.TranslateMessage(ctypes.byref(msg))
                _u.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()
            if hook:
                _u.UnhookWindowsHookEx(hook)

    def stop(self):
        self.stopping.set()
        if self.thread_id:
            _u.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self.thread.is_alive():
            self.thread.join(timeout=2)


class DesktopGuard:
    def __init__(self, app, interval=20):
        self.app = app
        self.interval = interval
        self._job = None
        self._running = False
        self._raised = False
        self._always_on_top = bool(getattr(app, "topmost", False))
        self._events = queue.SimpleQueue()
        self._watcher = None
        self._foreground = None
        self._repair_at = 0
        self._original = {}  # hwnd -> (owner, extended style)
        self._peek_original = {}
        self._failed = False

    def set_always_on_top(self, enabled):
        """Switch policy immediately; keep Peek/Show Desktop protection alive."""
        self._always_on_top = bool(enabled)
        self._raised = self._always_on_top
        # Clicks queued before toggling must not undo the new policy.
        while not self._events.empty():
            self._events.get()
        if IS_WIN:
            self._apply(self._handles())
        else:
            self.app.root.attributes("-topmost", self._always_on_top)
        self._repair_at = 0

    def start(self):
        if not IS_WIN or self._running:
            return
        self.app.root.update_idletasks()
        self._watcher = _MouseWatcher(self._events, self._handles())
        try:
            self._watcher.start()
        except Exception:
            self._watcher.stop()
            raise
        self._running = True
        self._foreground = _u.GetForegroundWindow()
        self._poll()

    def stop(self):
        self._running = False
        if self._job is not None:
            self.app.root.after_cancel(self._job)
            self._job = None
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        for hwnd, (owner, style) in self._original.items():
            if _u.IsWindow(hwnd):
                _set_long(hwnd, HWNDPARENT, owner)
                _set_long(hwnd, EXSTYLE, style)
        self._original.clear()
        for hwnd, value in self._peek_original.items():
            if _u.IsWindow(hwnd):
                flag = W.BOOL(value)
                _dwm.DwmSetWindowAttribute(hwnd, EXCLUDED_FROM_PEEK,
                                           ctypes.byref(flag), ctypes.sizeof(flag))
        self._peek_original.clear()

    def _handles(self):
        handles = []
        for widget in (self.app.root, self.app.settings_win,
                       self.app._add_win, self.app._font_picker):
            if (widget and widget.winfo_exists()
                    and (widget is self.app.root or widget.winfo_ismapped())):
                hwnd = _u.GetAncestor(widget.winfo_id(), ROOT)
                if hwnd and hwnd not in handles:
                    handles.append(hwnd)
        return handles

    def _is_own(self, hwnd, handles):
        seen = set()
        while hwnd and hwnd not in seen:
            if hwnd in handles:
                return True
            seen.add(hwnd)
            hwnd = _u.GetWindow(hwnd, OWNER)
        return False

    def _prepare(self, hwnd):
        shell = _u.GetShellWindow()
        if hwnd not in self._original:
            self._original[hwnd] = (_get_long(hwnd, HWNDPARENT),
                                    _get_long(hwnd, EXSTYLE))
        # Keep a top-level HWND, not a reparented child: Tk geometry, DPI and
        # transient dialogs remain intact. Reacquire a restarted Explorer.
        if shell and _get_long(hwnd, HWNDPARENT) != shell:
            ctypes.set_last_error(0)
            _set_long(hwnd, HWNDPARENT, shell)
            if ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
        style = _get_long(hwnd, EXSTYLE)
        desired = (style | TOOLWINDOW) & ~APPWINDOW
        if desired != style:
            ctypes.set_last_error(0)
            _set_long(hwnd, EXSTYLE, desired)
            if ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())

    def _apply(self, handles):
        if not handles:
            return
        main = handles[0]
        self._prepare(main)
        if self._watcher:
            # Pinned mode allows direct interaction, with no activation click.
            self._watcher.targets = () if self._always_on_top else tuple(handles)
        for hwnd in handles:
            self._exclude_from_peek(hwnd)
        if _u.IsIconic(main):
            _u.ShowWindow(main, 4)  # SW_SHOWNOACTIVATE
        elif not _u.IsWindowVisible(main):
            _u.ShowWindow(main, 8)  # SW_SHOWNA
        if self._always_on_top or self._raised:
            for hwnd in handles:
                if self._always_on_top or not _get_long(hwnd, EXSTYLE) & 0x8:
                    _position(hwnd, TOPMOST)
            return
        for hwnd in reversed(handles):
            if _get_long(hwnd, EXSTYLE) & 0x8:
                _position(hwnd, NOTOPMOST)
        anchor = _desktop_anchor(_windows())
        if anchor:
            _insert_above(main, anchor)
            for previous, hwnd in zip(handles, handles[1:]):
                _insert_above(hwnd, previous)

    def _exclude_from_peek(self, hwnd):
        # This is a set-only DWM attribute (Get returns E_INVALIDARG). These
        # are our own Tk windows, initially using Windows' default FALSE.
        value = W.BOOL(True)
        result = _dwm.DwmSetWindowAttribute(
            hwnd, EXCLUDED_FROM_PEEK, ctypes.byref(value), ctypes.sizeof(value))
        if result != 0:
            raise OSError(f"DwmSetWindowAttribute failed: {result:#x}")
        self._peek_original[hwnd] = False

    def _poll(self):
        self._job = None
        if not self._running:
            return
        try:
            handles = self._handles()
            clicked = False
            activate = None
            while not self._events.empty():
                event = self._events.get()
                target, swallowed = event if isinstance(event, tuple) else (event, False)
                self._raised = self._is_own(target, handles)
                activate = target if self._raised and swallowed else None
                clicked = True
            foreground = _u.GetForegroundWindow()
            # Alt+Tab and launching another app also release the overlay.
            if (not clicked and foreground != self._foreground and foreground
                    and not self._is_own(foreground, handles)):
                self._raised = False
                clicked = True
            self._foreground = foreground
            if self._always_on_top:
                self._raised = True
            now = time.monotonic()
            if clicked or now >= self._repair_at:
                self._apply(handles)
                if activate:
                    # A covered window may already be in the topmost band,
                    # underneath another topmost window. Explicitly reorder it.
                    _position(activate, TOPMOST)
                    _u.SetForegroundWindow(activate)
                self._repair_at = now + 0.25
            self._failed = False
        except Exception:
            if not self._failed:
                log.exception("Could not reconcile desktop window layers")
            self._failed = True
        finally:
            if self._running:
                self._job = self.app.root.after(self.interval, self._poll)
