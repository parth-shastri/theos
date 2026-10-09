"""Validate workout prescriptions and recorded sets."""

from typing import Literal

from pydantic import BaseModel, Field


class TrainingSet(BaseModel):
    repetitions: int = Field(ge=0, le=10000)
    weight_kg: float = Field(default=0, ge=0, le=1000)
    warmup: bool = False


class Exercise(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    set_details: list[TrainingSet] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)
    sets: int = Field(default=1, ge=1, le=100)
    repetitions: int = Field(default=0, ge=0, le=10000)
    weight_kg: float = Field(default=0, ge=0, le=1000)
    duration_minutes: float = Field(default=0, ge=0, le=1440)
    distance_km: float = Field(default=0, ge=0, le=1000)


TrainingType = Literal[
    "resistance", "zone2", "vo2", "sugarcane", "ruck", "recovery", "rest", "mobility", "other"
]


class TrainingDay(BaseModel):
    focus: str = ""
    session_type: TrainingType = "resistance"
    exercises: list[Exercise] = Field(default_factory=list, max_length=100)
    prescription: str = ""
    modality: str = ""
    target_zone: str = ""
    target_duration_minutes: float | None = Field(default=None, ge=0, le=1440)
    rules: dict = Field(default_factory=dict)
    notes: str = ""
