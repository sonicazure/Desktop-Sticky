"""Opt-in Windows integration test. Temporarily toggles Show Desktop twice.

Run from the repository root: python -m tests.native_layers
Uses only temporary Tk windows; never reads or writes user todo data.
"""
import ctypes
import threading
import tkinter as tk
from types import SimpleNamespace

from desktop_todo import dockguard as d
from desktop_todo.utils import enable_dpi_awareness


def run():
    enable_dpi_awareness()
    if not d.IS_WIN or not d._u.GetShellWindow():
        raise RuntimeError('An interactive Windows Explorer desktop is required')
    root = tk.Tk()
    root.title('Desktop Sticky layer test')
    root.overrideredirect(True)
    root.geometry('220x120+100+100')
    root.configure(bg='#f6e8ad')
    root.update()
    app = SimpleNamespace(root=root, settings_win=None,
                          _add_win=None, _font_picker=None)
    guard = d.DesktopGuard(app)
    toggled = False

    def pump(ms=400):
        root.after(ms, root.quit)
        root.mainloop()

    def topmost(hwnd):
        return bool(d._get_long(hwnd, d.EXSTYLE) & 8)

    def toggle_desktop():
        d._u.keybd_event.argtypes = [d.W.BYTE, d.W.BYTE, d.W.DWORD,
                                    ctypes.c_size_t]
        d._u.keybd_event(0x5B, 0, 0, 0)
        d._u.keybd_event(0x44, 0, 0, 0)
        d._u.keybd_event(0x44, 0, 2, 0)
        d._u.keybd_event(0x5B, 0, 2, 0)
        pump(700)

    try:
        guard.start()
        pump()
        main = guard._handles()[0]
        assert not topmost(main)
        windows = d._windows()
        assert windows.index(main) < windows.index(d._desktop_anchor(windows))
        print('PASS: startup above desktop, non-topmost', flush=True)
        guard._events.put(main)
        pump()
        assert topmost(main)
        pump()
        assert topmost(main)
        print('PASS: inside click raises and remains raised', flush=True)
        popup = tk.Toplevel(root)
        popup.title('Desktop Sticky test dialog')
        popup.transient(root)
        popup.geometry('180x100+120+140')
        app.settings_win = popup
        pump()
        assert all(topmost(h) for h in guard._handles())
        guard._events.put(d._u.GetShellWindow())
        pump()
        assert not any(topmost(h) for h in guard._handles())
        windows = d._windows()
        assert windows.index(guard._handles()[1]) < windows.index(main)
        print('PASS: popup follows raise/sink and stays above main', flush=True)
        popup.destroy()
        app.settings_win = None
        toggle_desktop()
        toggled = True
        assert d._u.IsWindowVisible(main) and not d._u.IsIconic(main)
        hit = d._u.WindowFromPoint(d.W.POINT(150, 150))
        assert d._u.GetAncestor(hit, d.ROOT) == main, ('desktop hit', hit, main)
        assert not topmost(main)
        print('PASS: Show Desktop leaves widget visible without topmost', flush=True)
        # Real mouse input exercises the hook thread and hit-testing, not just
        # the state queue. Click only temporary test windows; restore pointer.
        cursor = d.W.POINT()
        d._u.GetCursorPos(ctypes.byref(cursor))
        d._u.mouse_event.argtypes = [d.W.DWORD, d.W.DWORD, d.W.DWORD,
                                    d.W.DWORD, ctypes.c_size_t]
        try:
            def click():
                d._u.SetCursorPos(150, 150)
                d._u.mouse_event(2, 0, 0, 0, 0)
                d._u.mouse_event(4, 0, 0, 0, 0)
            worker = threading.Thread(target=click)
            root.after(50, worker.start)
            pump(600)
            worker.join(timeout=2)
            assert guard._raised and topmost(main)
            print('PASS: actual mouse click delivered through hook', flush=True)
        finally:
            d._u.SetCursorPos(cursor.x, cursor.y)
        guard._events.put(d._u.GetShellWindow())
        pump()
        toggle_desktop()
        toggled = False
        assert not topmost(main)
        print('PASS: desktop restore remains non-topmost', flush=True)
        other = tk.Tk()
        other.overrideredirect(True)
        other.title('Temporary external-window test')
        other.geometry('200x120+400+100')
        other.attributes('-topmost', True)
        try:
            pump()
            guard._events.put(main)
            pump()
            assert topmost(main)
            cursor = d.W.POINT()
            d._u.GetCursorPos(ctypes.byref(cursor))
            def outside_click():
                d._u.SetCursorPos(450, 150)
                d._u.mouse_event(2, 0, 0, 0, 0)
                d._u.mouse_event(4, 0, 0, 0, 0)
            worker = threading.Thread(target=outside_click)
            root.after(50, worker.start)
            pump(600)
            worker.join(timeout=2)
            d._u.SetCursorPos(cursor.x, cursor.y)
            assert not guard._raised and not topmost(main)
            print('PASS: actual outside click sinks the widget', flush=True)
            # Simulate a covered task card. Canvas tag bindings execute before
            # normal widget bindings, so this also catches late Tk filtering.
            canvas = tk.Canvas(root, width=220, height=120)
            canvas.pack(fill='both', expand=True)
            item = canvas.create_rectangle(0, 0, 220, 120, fill='yellow')
            actions = []
            canvas.tag_bind(item, '<Button-1>', lambda e: actions.append('tag'))
            canvas.bind('<ButtonRelease-1>', lambda e: actions.append('release'))
            other.geometry('200x120+220+100')
            other.deiconify()
            other.update()
            other_hwnd = d._u.GetAncestor(other.winfo_id(), d.ROOT)
            d._u.ShowWindow(other_hwnd, 9)
            pump()
            guard._events.put(main)
            pump()
            d._position(other_hwnd, d.TOPMOST)
            pump(100)
            assert d._covered(main, guard._handles())
            for expected in ([], ['tag', 'release']):
                worker = threading.Thread(target=click)
                root.after(50, worker.start)
                pump(600)
                worker.join(timeout=2)
                assert actions == expected, ('click actions', actions, expected)
                assert guard._raised and topmost(main)
            d._u.SetCursorPos(cursor.x, cursor.y)
            print('PASS: covered first click only raises; next click interacts', flush=True)
            guard.set_always_on_top(True)
            other.attributes('-topmost', False)
            def pinned_outside_click():
                d._u.SetCursorPos(350, 150)
                d._u.mouse_event(2, 0, 0, 0, 0)
                d._u.mouse_event(4, 0, 0, 0, 0)
            worker = threading.Thread(target=pinned_outside_click)
            root.after(50, worker.start)
            pump(600)
            worker.join(timeout=2)
            assert guard._raised and topmost(main)
            assert d._u.GetForegroundWindow() == other_hwnd
            popup = tk.Toplevel(root)
            popup.transient(root)
            app.settings_win = popup
            pump()
            assert all(topmost(h) for h in guard._handles())
            d._u.SetForegroundWindow(other_hwnd)
            pump()
            assert all(topmost(h) for h in guard._handles())
            assert d._u.GetForegroundWindow() == other_hwnd
            assert guard._watcher.targets == ()
            guard.set_always_on_top(False)
            assert not any(topmost(h) for h in guard._handles())
            assert guard._watcher.targets == tuple(guard._handles())
            popup.destroy()
            app.settings_win = None
            d._u.SetCursorPos(cursor.x, cursor.y)
            print('PASS: pinned mode survives app switching without stealing focus; disabling docks', flush=True)
        finally:
            other.destroy()
    finally:
        if toggled:
            toggle_desktop()
        guard.stop()
        assert guard._watcher is None
        root.destroy()


if __name__ == '__main__':
    run()
