from __future__ import annotations

from typing import Sequence

from .models import ClassificationInput

# Bump whenever the prompt text or rules change; stored with every classification.
PROMPT_VERSION = "2026-11-breadcrumb-v1"

ALLOWED_CATEGORIES = [
    "masove_vyrobky",
    "mliecne_vyrobky",
    "pekaren",
    "ovocie_zelenina",
    "napoje",
    "mrazene",
    "sladkosti",
    "ine",
]


def _as_input(product: str | ClassificationInput) -> ClassificationInput:
    return product if isinstance(product, ClassificationInput) else ClassificationInput(name=product)


def _line(index: int, product: ClassificationInput) -> str:
    if not product.retailer_category_path:
        return f"{index}. {product.name}"
    return f"{index}. {product.name} | retailer category: {' > '.join(product.retailer_category_path)}"


def build_classification_prompt(products: Sequence[str | ClassificationInput]) -> str:
    numbered_products = "\n".join(_line(index, _as_input(item)) for index, item in enumerate(products, start=1))
    categories = "\n".join(f"- {category}" for category in ALLOWED_CATEGORIES)
    return (
        "You are a food product classifier.\n"
        "Classify each input product into exactly one category.\n\n"
        "Allowed categories:\n"
        f"{categories}\n\n"
        "Rules:\n"
        "- Return only a JSON array of objects.\n"
        "- No markdown, no comments, no explanations.\n"
        "- Return exactly one object per input product.\n"
        "- Preserve product order from input.\n"
        "- Copy the exact original product name (without the retailer category) into `name`.\n"
        "- `category` must be exactly one value from the allowed list.\n"
        "- When a `retailer category` path is given, it is the primary signal: map that path to the\n"
        "  allowed categories. Use the product name only to resolve an ambiguous path. Do not let\n"
        "  descriptive words in the name override the path (e.g. 'Ovocie a zelenina > Pomaranče'\n"
        "  is `ovocie_zelenina` even if the name says 'džúsové').\n"
        "- `subcategory`: a short lowercase snake_case label for the most specific retailer\n"
        "  category (e.g. `parky`, `citrusy`), or null when no category path is given.\n"
        "- If uncertain, use `category` = `ine`.\n"
        "- `confidence` must be a number from 0 to 1. Lower it when the path and the name disagree\n"
        "  or when no path is given.\n"
        "- Do not add extra fields.\n"
        "- Confidence interpretation:\n"
        "  - 0.90 to 1.00: clear category\n"
        "  - 0.70 to 0.89: probable category\n"
        "  - 0.50 to 0.69: uncertain category\n"
        "  - 0.00 to 0.49: cannot be reliably categorized\n\n"
        "Input products:\n"
        f"{numbered_products}"
    )
