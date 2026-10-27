from pathlib import Path

from decouple import AutoConfig

# Reads backend/.env when present; real environment variables take precedence.
config = AutoConfig(search_path=Path(__file__).resolve().parents[1])
