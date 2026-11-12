from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Category = Literal[
    "masove_vyrobky",
    "mliecne_vyrobky",
    "pekaren",
    "ovocie_zelenina",
    "napoje",
    "mrazene",
    "sladkosti",
    "ine",
]


class ClassificationInput(BaseModel):
    """One product to classify: its name and, when known, the retailer's category path."""

    model_config = ConfigDict(extra="forbid")

    name: str
    retailer_category_path: list[str] = Field(default_factory=list)


class ProductClassification(BaseModel):
    name: str
    category: Category
    subcategory: str | None = None
    confidence: float = Field(ge=0, le=1)
    needs_review: bool | None = None


class ClassificationResponse(BaseModel):
    products: list[ProductClassification]
