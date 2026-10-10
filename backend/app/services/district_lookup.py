"""District name resolution for the India Flood Inventory tables.

The flood inventory (app/data/*.csv) keys districts by one spelling; Nominatim, the RIIS
district seed and users use others (Tuticorin / Thoothukkudi, Kanyakumari / Kanniyakumari,
Trichy / Tiruchirappalli). `app/data/district_lookup.json` is the maintained table

    canonical name -> {lgd_code, state, aliases[], parent?}

built by `python -m app.build_district_lookup` from the IFI event file's Districts and
District_LGD_Codes columns plus hand-kept aliases (see that script). Matching here is by
alias, case and punctuation insensitive. Every miss is reported through
monitoring.alert('district_miss', ...) when that module is importable, else logged.
"""
import json
import logging
import os
import re
import threading

log = logging.getLogger("riis.district_lookup")

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "district_lookup.json")

_STRIP_SUFFIXES = (" district", " dist", " zilla", " jilla")
_STRIP_PREFIXES = ("the ",)
_lock = threading.Lock()
_table = None       # {"districts": {...}, ...}
_index = None       # normalised alias -> canonical
_mtime = None


def normalise(name) -> str:
    """Case and punctuation insensitive key: 'Thoothukkudi District' -> 'thoothukkudi'."""
    s = str(name or "").strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()      # punctuation first, so 'Nilgiris District!' still loses its suffix
    for suf in _STRIP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s.replace(" ", "")


def _variants(name: str) -> list:
    s = str(name or "").strip().lower()
    out = [normalise(s)]
    for pre in _STRIP_PREFIXES:
        if s.startswith(pre):
            out.append(normalise(s[len(pre):]))
    # "Kanchipuram District, Tamil Nadu" -> first comma part
    if "," in s:
        out.append(normalise(s.split(",", 1)[0]))
    return [v for v in dict.fromkeys(out) if v]


def _load():
    global _table, _index, _mtime
    try:
        mtime = os.path.getmtime(DATA_PATH)
    except OSError:
        mtime = None
    if _table is not None and mtime == _mtime:
        return _table, _index
    with _lock:
        if _table is not None and mtime == _mtime:
            return _table, _index
        table, index = {"districts": {}}, {}
        if mtime is not None:
            try:
                with open(DATA_PATH, encoding="utf-8") as f:
                    table = json.load(f)
            except Exception as e:
                log.warning("district_lookup.json unreadable: %s", e)
        for canon, entry in (table.get("districts") or {}).items():
            index.setdefault(normalise(canon), canon)
            for v in _variants(canon):
                index.setdefault(v, canon)
            for alias in entry.get("aliases") or []:
                for v in _variants(alias):
                    index.setdefault(v, canon)
        _table, _index, _mtime = table, index, mtime
        return _table, _index


def _report_miss(name, state):
    detail = {"district": name, "state": state}
    try:
        from app.services.monitoring import alert
    except Exception:
        alert = None
    if alert is not None:
        try:
            alert("district_miss", detail)
            return
        except Exception as e:
            log.debug("monitoring.alert failed: %s", e)
    log.warning("district_miss: %s", detail)


def resolve(name, state=None, report: bool = True) -> dict | None:
    """Canonical IFI district for any spelling, or None (reported as a miss).

    Returns {"district", "lgd_code", "state", "parent", "matched_alias"}.
    """
    if not name or not str(name).strip():
        return None
    table, index = _load()
    districts = table.get("districts") or {}
    for v in _variants(name):
        canon = index.get(v)
        if canon is None:
            continue
        entry = districts.get(canon, {})
        # the same spelling can exist in two states (Aurangabad, Bilaspur, Hamirpur, Pratapgarh);
        # when a state is given and does not match, keep looking for a state-qualified alias
        if state and entry.get("state") and normalise(entry["state"]) != normalise(state):
            qualified = index.get(normalise(f"{name} {state}"))
            if qualified:
                canon, entry = qualified, districts.get(qualified, {})
        return {"district": canon, "lgd_code": entry.get("lgd_code"), "state": entry.get("state"),
                "parent": entry.get("parent"), "matched_alias": v}
    if report:
        _report_miss(name, state)
    return None


def table_size() -> int:
    table, _ = _load()
    return len(table.get("districts") or {})
