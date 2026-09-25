import pytest
from cp_helpers import make_world


@pytest.fixture
def small_world():
    return make_world([
        "..............",
        "..............",
        "..............",
        "....@.....V...",
        "..............",
        "..............",
    ], npcs={"V": "vendor"})
