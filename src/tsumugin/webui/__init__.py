"""Web UI 最小版 (read-only, FR-421〜424 縮小版)。

``create_app`` / ``serve`` を re-export する。両者は内部で fastapi/uvicorn を遅延 import
するため、この re-export 自体は optional extra ``web`` 未導入でも失敗しない (D6 遅延 import 契約)。
"""

from __future__ import annotations

from .app import create_app, serve

__all__ = ["create_app", "serve"]
