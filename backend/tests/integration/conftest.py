import inspect
from collections.abc import Iterator
from typing import Any

import pytest

from tests import helpers


@pytest.fixture(autouse=True)
def background_worker(request: pytest.FixtureRequest) -> Iterator[Any]:
    """Async API tests process background work (uploads, searches) via helpers.drain().

    Only async tests get a worker: sync tests have no Selector event loop to run it on.
    """
    if not inspect.iscoroutinefunction(request.function):
        yield None
        return
    worker = request.getfixturevalue("worker")
    helpers.CURRENT_WORKER = worker
    yield worker
    helpers.CURRENT_WORKER = None
