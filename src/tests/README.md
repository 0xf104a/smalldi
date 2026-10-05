# Tests for smalldi

This module contains tests for a smalldi library with the use of pytest

## Test structure
- `test_provide.py` - Tests for class `Provide`
- `test_injector.py` - Tests for class `Injector`
- `test_wrappers.py` - Tests for wrappers (currently only `staticclass`)
- `test_integration.py` - Library-level tests
- `test_container.py` - Tests for `Container`
- `test_interface.py` - Tests for interface bindings (`InterfaceTable`, `Injector.implements`, `Injector.override`)
