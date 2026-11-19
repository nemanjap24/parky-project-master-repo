from collections.abc import Sequence

from qwen_classifier.benchmark import _build_workload, benchmark
from qwen_classifier.models import ClassificationInput, ProductClassification


class FakeClassifier:
    model_name = "test-model"
    prompt_version = "test-prompt"

    def __init__(self) -> None:
        self.calls: list[list[ClassificationInput]] = []

    def classify(self, products: Sequence[ClassificationInput]) -> list[ProductClassification]:
        batch = list(products)
        self.calls.append(batch)
        return [
            ProductClassification(name=product.name, category="ine", confidence=0.5)
            for product in batch
        ]


def test_workload_repeats_only_when_requested() -> None:
    source = [ClassificationInput(name="A"), ClassificationInput(name="B")]

    assert [item.name for item in _build_workload(source, 5, True)] == ["A", "B", "A", "B", "A"]


def test_workload_rejects_implicit_repeats() -> None:
    source = [ClassificationInput(name="A")]

    try:
        _build_workload(source, 2, False)
    except ValueError as exc:
        assert "--repeat-input" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_benchmark_sends_one_sequential_request_per_product() -> None:
    classifier = FakeClassifier()
    products = [ClassificationInput(name=f"Product {index}") for index in range(3)]

    report = benchmark(products, classifier, progress_every=10)

    assert [len(call) for call in classifier.calls] == [1, 1, 1]
    assert report["completed_products"] == 3
    assert report["requests_in_flight"] == 1
    assert report["products_per_request"] == 1


def test_benchmark_stops_after_first_request_error() -> None:
    class FailingClassifier(FakeClassifier):
        def classify(self, products: Sequence[ClassificationInput]) -> list[ProductClassification]:
            self.calls.append(list(products))
            if len(self.calls) == 2:
                raise RuntimeError("simulated timeout")
            return [ProductClassification(name=products[0].name, category="ine", confidence=0.5)]

    classifier = FailingClassifier()
    products = [ClassificationInput(name=f"Product {index}") for index in range(4)]

    report = benchmark(products, classifier, progress_every=10)

    assert len(classifier.calls) == 2
    assert report["completed_products"] == 1
    assert report["failed_product"] == 2
    assert report["error"] == "simulated timeout"
