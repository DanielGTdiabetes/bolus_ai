
"""
Central location for constant values and tables used across the application.
"""

# Exercise Reduction Table
# Format: {intensity: {duration_minutes: reduction_percentage}}
EXERCISE_REDUCTION_TABLE = {
    "low": {60: 0.15, 120: 0.30},
    "moderate": {60: 0.30, 120: 0.55},
    "high": {60: 0.45, 120: 0.75},
}
