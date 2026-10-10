# Tests for smalldi

Tests use pytest. Run them from `src/`:

```shell
cd src && python -m pytest
```

## Test files
- `test_override_rules.py` — specification of singleton overrides: validation, conditional application (`when=...`), non-transitivity, freezing, circular dependencies
- `test_interface_bindings.py` — specification of interface bindings: implementations, overrides (including conditional overrides), freezing
- `test_injector_concurrency.py` — specification of threading behaviour: exactly-once construction, races between bindings and injection, deadlocks
- `test_injector.py` — `Injector` registration, injection and the deprecated `Injector.singletons_available`
- `test_provide.py` — the `Provide[T]` annotation as seen through `@Injector.inject`
- `test_container.py` — `Container` and `ComponentRegistration`
- `test_integration.py` — library-level scenarios with nested injection
- `test_concurrency.py` — `@synchronized` and `@threadsafe` from `smalldi.concurrency`
- `test_wrappers.py` — `staticclass`

The three specification files (`test_override_rules.py`, `test_interface_bindings.py`,
`test_injector_concurrency.py`) define the binding and threading semantics of the library. Where the
library disagrees with them, the test fails and the library is what needs changing.

`test_cross_thread_circular_dependency_does_not_deadlock` in `test_injector_concurrency.py` is skipped as a
known limitation: dependency cycles spanning several threads are not detected and may deadlock.

The `reset_injector` fixture from `conftest.py` isolates the injector registry between tests.
