import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi._interfaces import InterfaceResolver


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_resolver = Injector._interface_resolver
    old_overrides: Dict[Any, Any] = Injector._singleton_overrides.copy()

    Injector._singletons_available.clear()
    Injector._interface_resolver = InterfaceResolver()
    Injector._singleton_overrides.clear()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._interface_resolver = old_resolver
    Injector._singleton_overrides.clear()
    Injector._singleton_overrides.update(old_overrides)
