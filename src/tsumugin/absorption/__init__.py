"""透過吸収補正 v1 (TASK-0026 / D8 / FR-317)。

平板透過配置の吸収因子と、精密化に用いる吸収設定 dataclass を提供する層。
"""

from __future__ import annotations

from .model import AbsorptionConfig, transmission_factor

__all__ = ["AbsorptionConfig", "transmission_factor"]
