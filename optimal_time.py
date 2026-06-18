"""
Optimal posting time calculator for car education YouTube content.
Based on research into when car/automotive educational content performs best.
Adjusts to day of week for maximum reach.
"""

from datetime import datetime, timedelta
import pytz

# Research-based optimal posting windows for car education content
# Car audience: mostly male, 18-45, watches during commute, lunch, evening
# Times in EST
OPTIMAL_SCHEDULE = {
    0: {"hour": 8,  "minute": 0,  "reason": "Monday morning commute"},   # Monday
    1: {"hour": 12, "minute": 0,  "reason": "Tuesday lunch break"},       # Tuesday
    2: {"hour": 17, "minute": 0,  "reason": "Wednesday after work"},      # Wednesday
    3: {"hour": 8,  "minute": 0,  "reason": "Thursday morning commute"},  # Thursday
    4: {"hour": 15, "minute": 0,  "reason": "Friday afternoon"},          # Friday
    5: {"hour": 10, "minute": 0,  "reason": "Saturday morning"},          # Saturday
    6: {"hour": 11, "minute": 0,  "reason": "Sunday morning"},            # Sunday
}

def get_optimal_publish_time() -> dict:
    """
    Get the optimal publish time for today.
    Returns dict with scheduled_time (ISO format) and reason.
    """
    est = pytz.timezone("America/New_York")
    now = datetime.now(est)
    weekday = now.weekday()
    
    schedule = OPTIMAL_SCHEDULE[weekday]
    
    # Build target time today
    target = now.replace(
        hour=schedule["hour"],
        minute=schedule["minute"],
        second=0,
        microsecond=0
    )
    
    # If that time already passed today, post immediately
    if target <= now:
        target = now + timedelta(minutes=5)
    
    return {
        "scheduled_time_iso": target.isoformat(),
        "scheduled_time_readable": target.strftime("%A %B %d at %I:%M %p EST"),
        "reason": schedule["reason"],
        "post_immediately": (target - now).total_seconds() < 600,
    }


def get_privacy_and_schedule(publish_info: dict) -> dict:
    """
    Returns YouTube API-compatible publish settings.
    If posting immediately: public now.
    If scheduling: private with publishAt time.
    """
    if publish_info["post_immediately"]:
        return {
            "privacyStatus": "public",
            "publishAt": None,
        }
    else:
        return {
            "privacyStatus": "private",
            "publishAt": publish_info["scheduled_time_iso"],
        }


if __name__ == "__main__":
    info = get_optimal_publish_time()
    print(f"Optimal time: {info['scheduled_time_readable']}")
    print(f"Reason: {info['reason']}")
    print(f"Post immediately: {info['post_immediately']}")
