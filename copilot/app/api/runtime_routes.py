"""
Runtime Version API — 提供运行版本信息，解决版本冲突。
"""

import os
import time as _time

from flask import Blueprint, jsonify

runtime_bp = Blueprint("runtime", __name__)

_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()


@runtime_bp.route("/api/runtime/version", methods=["GET"])
def runtime_version():
    from app.config import (
        GRAPH_VERSION, PROMPT_VERSION, ROUTING_CONFIG_VERSION,
        TOOL_REGISTRY_VERSION, APP_VERSION, WEB_HOST, WEB_PORT,
    )
    import sys

    entrypoint = "unknown"
    main_module = sys.modules.get("__main__")
    if main_module and hasattr(main_module, "__file__") and main_module.__file__:
        fname = os.path.basename(main_module.__file__)
        entrypoint = fname

    return jsonify({
        "app_version": APP_VERSION,
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "routing_config_version": ROUTING_CONFIG_VERSION,
        "tool_registry_version": TOOL_REGISTRY_VERSION,
        "pid": _PID,
        "boot_time": _BOOT_TIME,
        "host": WEB_HOST,
        "port": WEB_PORT,
        "entrypoint": entrypoint,
        "execution_debug_enabled": True,
        "bad_case_enabled": True,
    })
