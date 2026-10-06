import pytest
from typing import Any, Dict

from smalldi import Injector


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector.singletons_available.copy()

    Injector.singletons_available.clear()

    yield

    Injector.singletons_available.clear()
    Injector.singletons_available.update(old_singletons)
