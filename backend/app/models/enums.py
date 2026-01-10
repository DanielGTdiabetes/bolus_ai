
from enum import Enum

class Trend(str, Enum):
    DOUBLE_UP = "DoubleUp"
    SINGLE_UP = "SingleUp"
    FORTY_FIVE_UP = "FortyFiveUp"
    FLAT = "Flat"
    FORTY_FIVE_DOWN = "FortyFiveDown"
    SINGLE_DOWN = "SingleDown"
    DOUBLE_DOWN = "DoubleDown"
    NOT_COMPUTABLE = "NOT COMPUTABLE"
    RATE_OUT_OF_RANGE = "RATE OUT OF RANGE"
    NONE = "NONE"

class ExerciseIntensity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"

class EventType(str, Enum):
    MEAL_BOLUS = "Meal Bolus"
    CORRECTION_BOLUS = "Correction Bolus"
    SNACK_BOLUS = "Snack Bolus"
    TEMP_BASAL = "Temp Basal"
    SITE_CHANGE = "Site Change"
    NOTE = "Note"
    EXERCISE = "Exercise"
