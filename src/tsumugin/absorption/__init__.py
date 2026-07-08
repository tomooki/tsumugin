"""透過吸収補正 v1 (TASK-0026 / D8 / FR-317)。

平板透過配置の吸収因子と、精密化に用いる吸収設定 dataclass を提供する層。
"""

from __future__ import annotations

from .model import AbsorptionConfig, transmission_factor
from .neutron import crystal_density, neutron_mu, neutron_mu_r

__all__ = [
    "AbsorptionConfig",
    "crystal_density",
    "neutron_mu",
    "neutron_mu_r",
    "transmission_factor",
]
