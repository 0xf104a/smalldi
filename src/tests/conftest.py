import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi._interface import InterfaceTable


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_interfaces = Injector._interfaces

    Injector._singletons_available.clear()
    Injector._interfaces = InterfaceTable()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._interfaces = old_interfaces
