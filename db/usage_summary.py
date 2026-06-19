"""Print anonymous public-MVP usage counts.

Run from the repo root:
    python -m db.usage_summary
"""
from __future__ import annotations

import json

from webapp.services import usage_summary


if __name__ == "__main__":
    print(json.dumps(usage_summary(days=7), indent=2))
