from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from production_besten.api.app import create_app  # noqa: E402

target = ROOT / "frontend" / "openapi.json"
app = create_app(engine=create_engine("sqlite://"), enable_dev_context=True)
target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OpenAPI exported to {target}")
