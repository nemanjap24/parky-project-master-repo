from qwen_classifier.prompts import build_classification_prompt


def test_build_classification_prompt_contains_numbered_products_and_rules() -> None:
    prompt = build_classification_prompt(["A", "B"])

    assert "1. A" in prompt
    assert "2. B" in prompt
    assert "- masove_vyrobky" in prompt
    assert "- ine" in prompt
    assert "0.90 to 1.00" in prompt
    assert "0.70 to 0.89" in prompt
    assert "0.50 to 0.69" in prompt
    assert "0.00 to 0.49" in prompt


def test_prompt_includes_retailer_category_path_as_primary_signal() -> None:
    from qwen_classifier.models import ClassificationInput

    prompt = build_classification_prompt(
        [
            ClassificationInput(
                name="Metro Chef Pomaranče džúsové",
                retailer_category_path=["Ovocie a zelenina", "Ovocie", "Citrusy", "Pomaranče"],
            ),
            "Bez kategórie",
        ]
    )

    assert "1. Metro Chef Pomaranče džúsové | retailer category: Ovocie a zelenina > Ovocie > Citrusy > Pomaranče" in prompt
    assert "2. Bez kategórie" in prompt
    assert "primary signal" in prompt


def test_prompt_version_is_set() -> None:
    from qwen_classifier.prompts import PROMPT_VERSION

    assert PROMPT_VERSION
