"""Versioned preset persistence with legacy settings migration."""
import json
import sys
from ..core.config import PRESETS_FILE
from ..core.recipe import Recipe


def _file():
    app = sys.modules.get('cake.ui.app')
    return getattr(app, 'PRESETS_FILE', PRESETS_FILE)


def load_presets() -> dict:
    try:
        raw = json.loads(_file().read_text(encoding='utf-8'))
        return {name: (Recipe.from_dict(value) if isinstance(value.get('retouch'), dict)
                       else Recipe.from_legacy(value)).to_dict()
                for name, value in raw.items()}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def save_presets(p: dict) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {name: (value if isinstance(value, Recipe) else Recipe.from_dict(value)
                   if isinstance(value.get('retouch'), dict) else Recipe.from_legacy(value)).to_dict()
            for name, value in p.items()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
