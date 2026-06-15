import os
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from supabase import create_client, Client

logger = logging.getLogger(__name__)

TAGS = ["WORK", "HOME", "LOVE", "FRIENDS", "TRAVEL", "SPORT", "MUSIC"]

TAG_EMOJIS = {
    "WORK": "💼",
    "HOME": "🏠",
    "LOVE": "❤️",
    "FRIENDS": "👥",
    "TRAVEL": "✈️",
    "SPORT": "🏃",
    "MUSIC": "🎵",
}

_raw_url = os.environ.get("SUPABASE_URL", "")
_supabase_key = os.environ.get("SUPABASE_KEY", "")

if not _raw_url or not _supabase_key:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_KEY must be set in environment variables"
    )

_parsed = urlparse(_raw_url)
SUPABASE_URL = f"{_parsed.scheme}://{_parsed.netloc}"

if not _parsed.scheme or not _parsed.netloc:
    raise ValueError(f"SUPABASE_URL is not a valid URL: {_raw_url!r}")

supabase: Client = create_client(SUPABASE_URL, _supabase_key)


def _to_iso(d: date) -> str:
    return d.isoformat()


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def get_user(user_id: int) -> dict | None:
    try:
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        if result.data:
            return result.data[0]
        return None
    except Exception as exc:
        logger.warning("get_user failed for user_id=%s: %s", user_id, exc)
        return None


def get_or_create_user(user_id: int, username: str, first_name: str) -> dict:
    existing = get_user(user_id)
    if existing:
        return existing

    new_user = {
        "id": user_id,
        "username": _safe_str(username),
        "first_name": _safe_str(first_name),
        "streak": 0,
        "xp": 0,
        "level": 1,
        "last_entry_date": None,
    }

    try:
        result = supabase.table("users").insert(new_user).execute()
        if result.data:
            return result.data[0]
        # Fallback: refetch in case of RLS/silent insert
        refetched = get_user(user_id)
        if refetched:
            return refetched
        return new_user
    except Exception as exc:
        logger.error(
            "get_or_create_user insert failed for user_id=%s: %s", user_id, exc
        )
        # Last resort: return a stub so caller can continue
        return dict(new_user)
        # Fallback: refetch in case of RLS/silent insert
        refetched = get_user(user_id)
        if refetched:
            return refetched
        return new_user
    except Exception as exc:
        logger.error(
            "get_or_create_user insert failed for user_id=%s: %s", user_id, exc
        )
        # Last resort: return a stub so caller can continue
        return dict(new_user)


def save_day_entry(
    user_id: int, entry_date: date, tags: list[str], note: str = ""
) -> dict:
    try:
        iso_date = _to_iso(entry_date)

        existing = (
            supabase.table("day_entries")
            .select("id")
            .eq("user_id", user_id)
            .eq("date", iso_date)
            .execute()
        )
        is_new = not bool(existing.data)

        payload = {
            "user_id": user_id,
            "date": iso_date,
            "tags": tags or [],
            "note": note or "",
        }

        if is_new:
            result = supabase.table("day_entries").insert(payload).execute()
            try:
                _update_user_stats(user_id, entry_date)
            except Exception as stats_exc:
                logger.warning(
                    "save_day_entry: stats update failed user_id=%s date=%s: %s",
                    user_id,
                    iso_date,
                    stats_exc,
                )
        else:
            result = (
                supabase.table("day_entries")
                .update({"tags": tags or [], "note": note or ""})
                .eq("user_id", user_id)
                .eq("date", iso_date)
                .execute()
            )

        if result.data:
            return result.data[0]
        # If insert returned no data (e.g. RLS), try to refetch
        return get_day_entry(user_id, entry_date) or {}
    except Exception as exc:
        logger.error(
            "save_day_entry failed user_id=%s date=%s: %s",
            user_id,
            _to_iso(entry_date),
            exc,
        )
        return {}


def _update_user_stats(user_id: int, entry_date: date) -> None:
    user = get_user(user_id)
    if not user:
        logger.warning("_update_user_stats: user not found user_id=%s", user_id)
        return

    last = user.get("last_entry_date")

    streak = int(user.get("streak") or 0)
    if last:
        try:
            last_date = (
                date.fromisoformat(last) if isinstance(last, str) else last
            )
        except (TypeError, ValueError):
            last_date = None

        if last_date == entry_date:
            # Same day duplicate, keep current streak
            pass
        elif last_date == entry_date - timedelta(days=1):
            streak += 1
        elif last_date is not None and last_date < entry_date - timedelta(days=1):
            streak = 1
        elif last_date is None:
            streak = 1
    else:
        streak = 1

    new_xp = int(user.get("xp") or 0) + 10
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
    except Exception as exc:
        logger.error(
            "_update_user_stats update failed user_id=%s date=%s: %s",
            user_id,
            _to_iso(entry_date),
            exc,
        )


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
    except Exception as exc:
        logger.warning(
            "get_day_entry failed user_id=%s date=%s: %s",
            user_id,
            _to_iso(entry_date),
            exc,
        )
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
    except Exception as exc:
        logger.warning(
            "get_month_entries failed user_id=%s year=%s month=%s: %s",
            user_id,
            year,
            month,
            exc,
        )
        return []


def add_goal(
    user_id: int, goal_type: str, period_start: str, title: str
) -> dict:
    try:
        payload = {
            "user_id": user_id,
            "type": goal_type,
            "period_start": period_start,
            "title": _safe_str(title),
            "completed": False,
        }
        result = supabase.table("goals").insert(payload).execute()
        if result.data:
            row = dict(result.data[0])
            # Normalize: DB column `type` -> bot-friendly `goal_type`
            row["goal_type"] = row.get("type", goal_type)
            return row
        return {"goal_type": goal_type, **payload}
    except Exception as exc:
        logger.error(
            "add_goal failed user_id=%s goal_type=%s: %s",
            user_id,
            goal_type,
            exc,
        )
        return {"goal_type": goal_type}


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
        goals = []
        for g in result.data or []:
            row = dict(g)
            # Normalize: copy DB column `type` into `goal_type` for bot code
            row["goal_type"] = row.get("type") or row.get("goal_type") or "day"
            goals.append(row)
        return goals
    except Exception as exc:
        logger.warning(
            "get_active_goals failed user_id=%s: %s", user_id, exc
        )
        return []


def complete_goal(user_id: int, goal_id: str, closing_note: str = "") -> bool:
    try:
        closed_iso = datetime.now(timezone.utc).isoformat()
        result = (
            supabase.table("goals")
            .update(
                {
                    "completed": True,
                    "closing_note": closing_note or "",
                    "closed_at": closed_iso,
                }
            )
            .eq("user_id", user_id)
            .eq("id", goal_id)
            .execute()
        )

        if result.data:
            try:
                user = get_user(user_id)
                if user:
                    new_xp = int(user.get("xp") or 0) + 25
                    level = max(1, (new_xp // 100) + 1)
                    supabase.table("users").update(
                        {"xp": new_xp, "level": level}
                    ).eq("id", user_id).execute()
            except Exception as xp_exc:
                logger.warning(
                    "complete_goal: XP update failed user_id=%s goal_id=%s: %s",
                    user_id,
                    goal_id,
                    xp_exc,
                )
            return True
        return False
    except Exception as exc:
        logger.error(
            "complete_goal failed user_id=%s goal_id=%s: %s",
            user_id,
            goal_id,
            exc,
        )
        return False


def get_user_stats(user_id: int) -> dict | None:
    try:
        user = get_user(user_id)
        if not user:
            return None

        today = date.today()
        year_start = today.replace(month=1, day=1).isoformat()

        total_resp = (
            supabase.table("day_entries")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        total_entries = len(total_resp.data or [])

        year_resp = (
            supabase.table("day_entries")
            .select("id")
            .eq("user_id", user_id)
            .gte("date", year_start)
            .execute()
        )
        year_entries = len(year_resp.data or [])

        goals_resp = (
            supabase.table("goals").select("id").eq("user_id", user_id).execute()
        )
        total_goals = len(goals_resp.data or [])

        completed_resp = (
            supabase.table("goals")
            .select("id")
            .eq("user_id", user_id)
            .eq("completed", True)
            .execute()
        )
        completed_goals = len(completed_resp.data or [])

        return {
            "user": user,
            "total_entries": total_entries,
            "year_entries": year_entries,
            "total_goals": total_goals,
            "completed_goals": completed_goals,
        }
    except Exception as exc:
        logger.error("get_user_stats failed user_id=%s: %s", user_id, exc)
        # Return a safe default with whatever we can show
        try:
            user = get_user(user_id)
        except Exception:
            user = None
        if not user:
            return None
        return {
            "user": user,
            "total_entries": 0,
            "year_entries": 0,
            "total_goals": 0,
            "completed_goals": 0,
        }