"""NAV data from the free mfapi.in API, with a disk cache."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

API = "https://api.mfapi.in/mf"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "nav"
CACHE_MAX_AGE_S = 12 * 3600
TIMEOUT_S = 30


class NavError(RuntimeError):
    pass


def search_funds(query: str) -> list[dict]:
    """Return [{'schemeCode': int, 'schemeName': str}, ...]."""
    query = query.strip()
    if len(query) < 2:
        return []
    try:
        r = requests.get(f"{API}/search", params={"q": query}, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json() or []
    except requests.RequestException as exc:
        raise NavError(f"Fund search failed: {exc}") from exc


def _cache_file(code: int) -> Path:
    return CACHE_DIR / f"{int(code)}.json"


def _fetch_raw(code: int, force: bool = False) -> dict:
    path = _cache_file(code)
    if not force and path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE_S:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        r = requests.get(f"{API}/{int(code)}", timeout=TIMEOUT_S)
        r.raise_for_status()
        raw = r.json()
    except requests.RequestException as exc:
        if path.exists():  # use old data when offline
            return json.loads(path.read_text(encoding="utf-8"))
        raise NavError(f"NAV download failed for scheme {code}: {exc}") from exc
    if not raw.get("data"):
        raise NavError(f"No NAV data for scheme {code}.")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return raw


def get_nav(code: int, force: bool = False) -> tuple[dict, pd.Series]:
    """Return (meta, nav series). The series has a sorted DatetimeIndex."""
    raw = _fetch_raw(code, force)
    dates, navs = [], []
    for row in raw["data"]:
        try:
            nav = float(row["nav"])
        except (TypeError, ValueError):
            continue
        if nav <= 0:
            continue
        dates.append(datetime.strptime(row["date"], "%d-%m-%Y"))
        navs.append(nav)
    s = pd.Series(navs, index=pd.DatetimeIndex(dates), name="nav").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty:
        raise NavError(f"No valid NAV data for scheme {code}.")
    return raw.get("meta", {}), s
