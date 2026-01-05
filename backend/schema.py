from typing import List, Optional, Literal
from pydantic import BaseModel, Field

Unit = Literal["g", "ml", "tsp", "tbsp", "cup", "piece", "slice"]

class Ingredient(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[Unit] = None
    descriptor: Optional[str] = None
    confidence: float = Field(ge=0, le=1)

class Cooking(BaseModel):
    oil_or_fat: List[str] = Field(default_factory=list)
    method: Optional[str] = None

class Dish(BaseModel):
    dish_name: str
    dish_type: Literal["simple", "composite"]
    quantity: Optional[float] = None
    unit: Optional[Unit] = None
    ingredients: List[Ingredient] = Field(default_factory=list)
    cooking: Cooking = Field(default_factory=Cooking)
    notes: List[str] = Field(default_factory=list)

class ParseResult(BaseModel):
    raw_text: str
    language: Literal["en", "ar", "mixed"] = "mixed"
    dishes: List[Dish]
    missing_info: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence_overall: float = Field(ge=0, le=1)
