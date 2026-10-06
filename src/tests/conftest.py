import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi import container
from smalldi._interface import InterfaceTable


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector and Container state before and after each test"""
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_interfaces = Injector._interfaces
    old_registrations = container._registrations.copy()
    old_instances = container._instances.copy()

    Injector._singletons_available.clear()
    Injector._interfaces = InterfaceTable()
    container._registrations.clear()
    container._instances.clear()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._interfaces = old_interfaces
    container._registrations[:] = old_registrations
    container._instances[:] = old_instances
