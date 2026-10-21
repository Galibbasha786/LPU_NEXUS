# crisis/constants.py

# Incident categories
CATEGORIES = [
    ("medical",     "Medical Emergency"),
    ("fire",        "Fire / Smoke"),
    ("security",    "Security Threat"),
    ("accident",    "Accident"),
    ("electrical",  "Electrical / Hazard"),
    ("flood",       "Flooding / Waterlogging"),
    ("crowd",       "Dangerous Crowd"),
    ("infra",       "Structural / Infra Failure"),
    ("other",       "Other"),
]

SEVERITIES = [
    ("low",      "Low"),
    ("medium",   "Medium"),
    ("high",     "High"),
    ("critical", "Critical"),
]

STATUSES = [
    ("reported",     "Reported"),
    ("verified",     "Verified"),
    ("assigned",     "Assigned"),
    ("responding",   "Responding"),
    ("contained",    "Contained"),
    ("resolved",     "Resolved"),
    ("false_alarm",  "False Alarm"),
]

# Status → who can transition where
STAFF_TRANSITIONS = {
    "reported":   ["verified", "assigned", "false_alarm"],
    "verified":   ["assigned", "responding", "false_alarm"],
    "assigned":   ["responding", "contained"],
    "responding": ["contained", "resolved"],
    "contained":  ["resolved"],
    "resolved":   [],
    "false_alarm": [],
}

# Only admin can do these
ADMIN_ONLY_STATUSES = ["false_alarm", "resolved"]