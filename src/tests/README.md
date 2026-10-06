# Tests for smalldi

This module contains tests for a smalldi library with the use of pytest

## Test structure
- `test_provide.py` - Tests for class `Provide`
- `test_injector.py` - Tests for class `Injector`
- `test_interfaces.py` - Tests for interfaces (`@Injector.interface`, `@Injector.implements`, `InterfaceResolver`)
- `test_singleton.py` - Tests for lazy singletons (`LazySingleton`): laziness, overrides and freezing
- `test_concurrency.py` - Tests for `@synchronized` and `@threadsafe`
- `test_wrappers.py` - Tests for wrappers (currently only `staticclass`)
- `test_integration.py` - Library-level tests
- `test_container.py` - Tests for `Container`

The `reset_injector` fixture from `conftest.py` isolates the injector registry between tests.
