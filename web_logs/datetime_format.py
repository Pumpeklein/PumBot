from __future__ import annotations

import sys
from pathlib import Path

try:
    from src.pumbot.utils.datetime_format import (
        berlin_today,
        format_berlin_date,
        format_berlin_datetime,
    )
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from src.pumbot.utils.datetime_format import (
        berlin_today,
        format_berlin_date,
        format_berlin_datetime,
    )


__all__ = ["berlin_today", "format_berlin_date", "format_berlin_datetime"]
