import pytest

from tools.submit_giggle_image_manifest import validate_reference_count


@pytest.mark.parametrize("count", [0, 11, 12, 13])
def test_invalid_reference_count_is_blocked(count):
    task = {"task_key": "TEST", "reference_images": ["image.png"] * count}
    with pytest.raises(ValueError, match="1..10"):
        validate_reference_count(task)
    assert len(task["reference_images"]) == count


@pytest.mark.parametrize("count", [1, 10])
def test_supported_count_is_accepted(count):
    validate_reference_count({"reference_images": ["image.png"] * count})
