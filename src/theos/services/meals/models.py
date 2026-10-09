"""Validate meal input before storage or export."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Meal(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    calories: float = Field(ge=0, le=20000)
    protein: float | None = Field(default=None, ge=0, le=2000)
    carbohydrates: float | None = Field(default=None, ge=0, le=2000)
    fat: float | None = Field(default=None, ge=0, le=2000)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    eaten_at: datetime
