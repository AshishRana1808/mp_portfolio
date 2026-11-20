"""Save and load portfolios as JSON files."""
from __future__ import annotations

import json
import re
from pathlib import Path

PORTFOLIO_DIR = Path(__file__).resolve().parent.parent / "portfolios"


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip()
    return s or "portfolio"


def list_portfolios() -> list[str]:
    PORTFOLIO_DIR.mkdir(exist_ok=True)
    return sorted(p.stem for p in PORTFOLIO_DIR.glob("*.json"))


def load_portfolio(name: str) -> dict:
    return json.loads((PORTFOLIO_DIR / f"{_safe(name)}.json").read_text(encoding="utf-8"))


def save_portfolio(pf: dict) -> str:
    PORTFOLIO_DIR.mkdir(exist_ok=True)
    name = _safe(pf.get("name") or "portfolio")
    pf["name"] = name
    (PORTFOLIO_DIR / f"{name}.json").write_text(json.dumps(pf, indent=2, default=str), encoding="utf-8")
    return name


def delete_portfolio(name: str) -> None:
    p = PORTFOLIO_DIR / f"{_safe(name)}.json"
    if p.exists():
        p.unlink()
