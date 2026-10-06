import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi._interface import InterfaceTable


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_interfaces = Injector._interfaces
    old_overrides: Dict[Any, Any] = Injector._singleton_overrides.copy()
    old_frozen = Injector._singletons_frozen.copy()

    Injector._singletons_available.clear()
    Injector._singleton_overrides.clear()
    Injector._singletons_frozen.clear()
    Injector._interfaces = InterfaceTable()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._singleton_overrides.clear()
    Injector._singleton_overrides.update(old_overrides)
    Injector._singletons_frozen.clear()
    Injector._singletons_frozen.update(old_frozen)
    Injector._interfaces = old_interfaces
