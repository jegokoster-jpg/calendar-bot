import os
import calendar
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from supabase import create_client, Client

TAGS = ["WORK", "HOME", "LOVE", "FRIENDS", "TRAVEL", "SPORT", "MUSIC"]

TAG_EMOJIS = {
    "WORK": "рџ’ј",
    "HOME": "рџЏ ",
    "LOVE": "вќ¤пёЏ",
    "FRIENDS": "рџ‘Ґ",
    "TRAVEL": "вњ€пёЏ",
    "SPORT": "рџЏѓ",
    "MUSIC": "рџЋµ",
}

_raw_url = os.environ.get("SUPABASE_URL", "")
_supabase_key = os.environ.get("SUPABASE_KEY", "")

if not _raw_url or not _supabase_key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

_parsed = urlparse(_raw_url)
SUPABASE_URL = f"{_parsed.scheme}://{_parsed.netloc}"

supabase: Client = create_client(SUPABASE_URL, _supabase_key)


def _to_iso(d: date) -> str:
    return d.isoformat()


def get_user(user_id: int) -> dict | None:
    try:
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_or_create_user(user_id: int, username: str, first_name: str) -> dict:
    existing = get_user(user_id)
    if existing:
        return existing

    new_user = {
        "id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "streak": 0,
        "xp": 0,
        "level": 1,
        "last_entry_date": None,
    }

    try:
        result = supabase.table("users").insert(new_user).execute()
        return result.data[0] if result.data else {}
    except Exception:
        return {}


def save_day_entry(
    user_id: int, entry_date: date, tags: list[str], note: str = ""
) -> dict:
    try:
        existing = (
            supabase.table("day_entries")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", _to_iso(entry_date))
            .execute()
        )
        is_new = not bool(existing.data)

        payload = {
            "user_id": user_id,
            "date": _to_iso(entry_date),
            "tags": tags,
            "note": note,
        }

        if is_new:
            result = supabase.table("day_entries").insert(payload).execute()
            _update_user_stats(user_id, entry_date)
        else:
            result = (
                supabase.table("day_entries")
                .update({"tags": tags, "note": note})
                .eq("user_id", user_id)
                .eq("date", _to_iso(entry_date))
                .execute()
            )

        return result.data[0] if result.data else {}
    except Exception:
        return {}


def _update_user_stats(user_id: int, entry_date: date) -> None:
    user = get_user(user_id)
    if not user:
        return

    today = date.today()
    last = user.get("last_entry_date")

    streak = user.get("streak", 0)
    if last:
        last_date = date.fromisoformat(last) if isinstance(last, str) else last
        if last_date == today - timedelta(days=1):
            streak += 1
        elif last_date < today:
            streak = 1
    else:
        streak = 1

    new_xp = user.get("xp", 0) + 10
    level = max(1, (new_xp // 100) + 1)

    try:
        supabase.table("users").update(
            {
                "streak": streak,
                "xp": new_xp,
                "level": level,
                "last_entry_date": _to_iso(entry_date),
            }
        ).eq("id", user_id).execute()
    except Exception:
        pass


def get_day_entry(user_id: int, entry_date: date) -> dict | None:
    try:
        result = (
            supabase.table("day_entries")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", _to_iso(entry_date))
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_month_entries(user_id: int, year: int, month: int) -> list[dict]:
    try:
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last_day)

        result = (
            supabase.table("day_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("date", _to_iso(start))
            .lte("date", _to_iso(end))
            .execute()
        )
        return result.data if result.data else []
    except Exception:
        return []


def add_goal(
    user_id: int, goal_type: str, period_start: str, title: str
) -> dict:
    try:
        payload = {
            "user_id": user_id,
            "type": goal_type,
            "period_start": period_start,
            "title": title,
            "completed": False,
        }
        result = supabase.table("goals").insert(payload).execute()
        return result.data[0] if result.data else {}
    except Exception:
        return {}


def get_active_goals(user_id: int) -> list[dict]:
    try:
        result = (
            supabase.table("goals")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", False)
            .order("created_at", desc=True)
            .execute()
        )
        # normalize: return 'goal_type' key for bot compatibility
        goals = []
        for g in (result.data or []):
            g["goal_type"] = g.get("type", "day")
            goals.append(g)
        return goals
    except Exception:
        return []


def complete_goal(user_id: int, goal_id: str, closing_note: str = "") -> bool:
    try:
        result = (
            supabase.table("goals")
            .update(
                {
                    "completed": True,
                    "closing_note": closing_note,
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("user_id", user_id)
            .eq("id", goal_id)
            .execute()
        )

        if result.data:
            user = get_user(user_id)
            if user:
                new_xp = user.get("xp", 0) + 25
                level = max(1, (new_xp // 100) + 1)
                supabase.table("users").update(
                    {"xp": new_xp, "level": level}
                ).eq("id", user_id).execute()

        return bool(result.data)
    except Exception:
        return False


def get_user_stats(user_id: int) -> dict | None:
    try:
        user = get_user(user_id)
        if not user:
            return None

        year_start = date.today().replace(month=1, day=1).isoformat()

        total_entries = len(
            supabase.table("day_entries").select("id").eq("user_id", user_id).execute().data or []
        )
        year_entries = len(
            supabase.table("day_entries").select("id")
            .eq("user_id", user_id).gte("date", year_start).execute().data or []
        )
        total_goals = len(
            supabase.table("goals").select("id").eq("user_id", user_id).execute().data or []
        )
        completed_goals = len(
            supabase.table("goals").select("id")
            .eq("user_id", user_id).eq("completed", True).execute().data or []
        )

        return {
            "user": user,
            "total_entries": total_entries,
            "year_entries": year_entries,
            "total_goals": total_goals,
            "completed_goals": completed_goals,
        }
    except Exception:
        return None
