"""Entry point for Streamlit Cloud / Hugging Face Spaces."""
from pathlib import Path
import importlib.util

_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
_spec = importlib.util.spec_from_file_location("momentum_dashboard", _path)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
