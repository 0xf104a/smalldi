import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi._interfaces import InterfaceResolver


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_resolver = Injector._interface_resolver

    Injector._singletons_available.clear()
    Injector._interface_resolver = InterfaceResolver()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._interface_resolver = old_resolver
