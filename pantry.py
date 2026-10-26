"""Second Helping: pantry logic (no UI code, so it is easy to test)."""
import json
from datetime import date, datetime, timedelta

EMPTY = {"items": [], "used": 0, "gave": 0, "tossed": 0, "api_key": "",
         "provider": "gemini"}
ORDER = {"now": 0, "soon": 1, "give": 2, "ok": 3}


KEY = "second_helping_v1"


def load(storage):
    """storage is any object with get(key) and set(key, value), such as
    Flet's page.client_storage (browser storage on web, app storage on phones)."""
    try:
        data = json.loads(storage.get(KEY) or "")
        if isinstance(data.get("items"), list):
            return {**EMPTY, **data}
    except (ValueError, TypeError, AttributeError):
        pass
    return {**EMPTY, "items": []}


def save(storage, state):
    try:
        storage.set(KEY, json.dumps(state))
    except Exception:
        pass


def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def days_left(iso, today=None):
    return (date.fromisoformat(iso) - (today or date.today())).days


def status(item, today=None):
    """Return (level, label, hint) for one pantry item."""
    d = days_left(item["date"], today)
    if d < 0:
        n = -d
        return ("now", f"Past date {n} day{'s' if n != 1 else ''} ago",
                "Check it carefully. If it looks or smells off, throw it out.")
    if d <= 3:
        label = "Today" if d == 0 else "Tomorrow" if d == 1 else f"{d} days left"
        return ("now", label, "Plan a meal with this soon.")
    if d <= 14:
        return ("soon", f"{d} days left", "Use it in the next week or two.")
    if item["type"] == "shelf" and d <= 60:
        return ("give", f"{d} days left",
                "Won't use it? A food bank can. Donate while it has time left.")
    return ("ok", f"{d} days left", "")


def can_donate(item, today=None):
    return item["type"] == "shelf" and days_left(item["date"], today) >= 0


def sort_items(items, today=None):
    return sorted(items, key=lambda i: (ORDER[status(i, today)[0]],
                                        days_left(i["date"], today)))


def parse_items(text, today=None):
    """Turn the scanner's JSON reply into pantry items the user can review.

    Each item has "read": True if the date was printed on the label, and False
    if the date is only an estimate from typical shelf life.
    """
    today = today or date.today()
    s, e = text.find("["), text.rfind("]")
    if s == -1 or e <= s:
        return []
    try:
        raw = json.loads(text[s:e + 1])
    except ValueError:
        return []
    out, seen = [], set()
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()[:50]
        if not name or name.lower() in seen:
            continue
        kind = "fresh" if r.get("type") == "fresh" else "shelf"
        d = parse_date(str(r.get("best_by") or ""))
        read = d is not None
        if d is None:
            try:
                life = int(r.get("shelf_life_days"))
            except (TypeError, ValueError):
                life = 7 if kind == "fresh" else 180
            d = today + timedelta(days=max(1, min(life, 730)))
        seen.add(name.lower())
        out.append({"name": name, "type": kind, "date": d.isoformat(), "read": read})
    return out
