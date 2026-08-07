# -*- coding: utf-8 -*-
"""数据目录定位与 JSON 原子读写（写临时文件再替换 + .bak 备份）。"""
import json
import os
import shutil
import sys

from .constants import APP_NAME


def _script_dir():
    """入口脚本所在目录（作为数据目录的最后候选）。"""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    if path:
        return os.path.dirname(os.path.abspath(path))
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def _data_dir():
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), APP_NAME),
        os.path.join(os.path.expanduser("~"), "." + APP_NAME),
        _script_dir(),
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
    return _script_dir()


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
