# navigation/peak_hour.py
from datetime import datetime
from core.mongo import route_history


# Campus class-change windows (LPU typical)
PEAK_WINDOWS = [
    (8, 30, 9, 0),
    (9, 50, 10, 10),
    (11, 10, 11, 30),
    (12, 30, 13, 0),
    (13, 50, 14, 10),
    (15, 10, 15, 30),
    (16, 50, 17, 10),
]


def get_congestion_for_route(from_name, to_name, at_time=None):
    """Determine congestion level for a route at a given time."""
    now = at_time or datetime.now()

    rule_level = _rule_based_level(now)
    data_level = _historical_level(from_name, to_name, now)

    order = {"low": 0, "moderate": 1, "high": 2, "severe": 3}
    combined = max(order[rule_level], order[data_level])
    level = [k for k, v in order.items() if v == combined][0]

    return {
        "level": level,
        "source": "rule+data" if data_level != "low" else "rule",
        "hour": now.hour,
        "minute": now.minute,
        "timestamp": now.isoformat(),
    }


def _rule_based_level(dt):
    """Class-change windows are high congestion."""
    h, m = dt.hour, dt.minute
    for (sh, sm, eh, em) in PEAK_WINDOWS:
        if (h, m) >= (sh, sm) and (h, m) <= (eh, em):
            return "high"
    if h < 8 or h >= 20:
        return "low"
    return "moderate"


def _historical_level(from_name, to_name, dt):
    """Check route_history for congestion patterns at this hour."""
    docs = list(route_history().find({
        "from_location": from_name,
        "to_location": to_name,
        "hour": dt.hour,
    }))

    if not docs:
        return "low"

    avg = sum(d.get("congestion_score", 1) for d in docs) / len(docs)

    if avg >= 3.5:
        return "severe"
    elif avg >= 2.5:
        return "high"
    elif avg >= 1.5:
        return "moderate"
    return "low"


def record_route_congestion(from_name, to_name, congestion_level):
    """Called when a student reports congestion. Learns for future."""
    score_map = {"low": 1, "moderate": 2, "high": 3, "severe": 4}
    now = datetime.now()

    route_history().insert_one({
        "from_location": from_name,
        "to_location": to_name,
        "hour": now.hour,
        "day_of_week": now.weekday(),
        "congestion_score": score_map.get(congestion_level, 1),
        "recorded_at": now,
    })