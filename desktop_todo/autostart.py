# -*- coding: utf-8 -*-
"""开机自启动（Windows 注册表 Run 键），含入口脚本路径解析。"""
import os
import sys

from .constants import APP_NAME


def entry_script():
    """当前程序入口脚本的绝对路径（exe 打包时回退到 argv[0]）。"""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    if path:
        return os.path.abspath(path)
    return os.path.abspath(sys.argv[0])


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
                              f'"{exe}" "{entry_script()}"')
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
