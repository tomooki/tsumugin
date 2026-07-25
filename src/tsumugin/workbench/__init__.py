"""操作系デスクトップワークベンチ (`tsumugin.workbench`) — FastAPI × React、Tauri 配布。

③ 層 (最終判断者) を人間 (MANUAL) と LLM (AUTO) で切り替える操作系 GUI のバックエンド
(`docs/spec/gui-workbench/requirements.md` / `docs/design/gui-workbench/architecture.md`)。
既存の read-only `tsumugin.webui` (REQ-007) とは別パッケージに分離し、read-only 保証を
構造的に維持する (NFR-GUI-004)。

コア import 非汚染 (NFR-GUI-005): 本 `__init__` は `WorkbenchSession` のみを再エクスポートし、
fastapi/uvicorn を import しない (`app.py` が遅延 import する)。
"""

from __future__ import annotations

from .session import WorkbenchSession

__all__ = ["WorkbenchSession"]
