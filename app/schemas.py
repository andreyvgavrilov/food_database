from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngredientLookupRequest(BaseModel):
    ingredient_name: str
    preferred_food_category: str | None = None
    max_results: int = Field(default=5, ge=1, le=20)


class RecipeIngredient(BaseModel):
    name: str
    quantity: float
    unit: str = "gram"


class NutritionCalculationRequest(BaseModel):
    ingredients: list[RecipeIngredient]
    servings: float | None = Field(default=None, gt=0)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    raw: Any | None = None
