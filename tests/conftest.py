import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a saved Companies House JSON response by filename (no extension)."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())