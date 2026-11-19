from qwen_classifier.models import ClassificationInput
from scraper.prompt_batch_benchmark import BATCH_SIZES, PRODUCT_COUNT, _batches


def test_batch_sizes_cover_100_products_with_expected_request_counts() -> None:
    products = [ClassificationInput(name=f"Product {index}") for index in range(PRODUCT_COUNT)]

    batches_by_size = {size: _batches(products, size) for size in BATCH_SIZES}

    assert [len(batches_by_size[5]), len(batches_by_size[10]), len(batches_by_size[15])] == [20, 10, 7]
    assert [len(batches_by_size[15][-1]), len(batches_by_size[10][-1])] == [10, 10]
    assert all(sum(map(len, batches)) == PRODUCT_COUNT for batches in batches_by_size.values())
