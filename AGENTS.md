# AGENTS.md

Guidance for AI coding agents working on this repository.

## Project

`smalldi` is a tiny, annotation-driven dependency injection library for Python (>=3.11).
Its only runtime dependency is `typing-extensions`. Keep it small: avoid new dependencies and
avoid adding features that aren't requested.

## Layout

```
src/
  smalldi/
    __init__.py     # Injector (singletons, @inject, @implements, @override), re-exports Provide
    annotation.py   # Provide[T] (= Annotated[T, _Provide]) and annotation parsing
    container.py    # Container base class, ComponentRegistration
    collector.py    # Collector.collect_from_package: imports modules to trigger decorators
    wrappers.py     # @staticclass (forbids instantiation)
    _interface.py   # InterfaceTable (private); its exceptions are re-exported from smalldi
    _singleton.py   # LazySingleton (private), global singleton creation lock
    concurrency.py  # @threadsafe, @threadsafe_fn, @threadsafe_cls (reentrant locks)
    py.typed
  tests/            # pytest suite, one file per module (see src/tests/README.md)
pyproject.toml      # hatchling build, package metadata
CHANGELOG.md
```

## Commands

All commands run from `src/` (CI does the same):

```sh
cd src
pytest            # run tests
pylint -E smalldi # lint (errors only), as in CI
```

A local virtualenv may exist at `.venv/` in the repo root (`../.venv/bin/pytest` from `src/`).

CI (`.github/workflows/python-package.yml`) runs both on Python 3.11, 3.12 and 3.13.
Publishing to PyPI happens on GitHub release (`.github/workflows/publish.yaml`).

## How the library works (things that are easy to get wrong)

- `Injector` is a static class: never instantiate it. State lives in class attributes:
  `Injector._singletons_available` (`type -> LazySingleton`; `.get()` returns the instance) and
  `Injector._interfaces` (an `InterfaceTable`). The public `Injector.singletons_available` is a deprecated alias (on the
  metaclass) that emits `DeprecationWarning`; don't use it in library code or tests.
- `@Injector.singleton` only registers the class; it is instantiated **lazily, on first injection**
  (`LazySingleton.get()`). Its `__init__` must take no arguments other than `Provide[...]` ones
  injected via `@Injector.inject`. Creation freezes the singleton. All singletons are created under
  one global reentrant lock, so circular dependencies raise `TypeError` even across threads.
  Registering the same class twice raises `ValueError`. Singletons must not mutate user classes.
- `@Injector.inject` reads `Provide[T]` annotations at decoration time but resolves them **on the
  first call** (then caches them), so definition order doesn't matter. A missing dependency raises
  `TypeError("Singleton ... is not available")` on call. Tests that check freezing must call the
  function first.
- `@Injector.implements(Iface)` and `@Injector.override(Iface)` must be applied above
  `@Injector.singleton`. Each interface has one baseline (`implements`) and at most one override,
  in either declaration order; the override wins. A second, different class in either slot raises
  `InterfaceAlreadyBoundError`. The first lookup freezes the resolved implementation; any binding
  that would change it afterwards raises `InterfaceFrozenError`. A key can't be both a singleton and
  an interface: binding to a singleton key, or registering a used interface as a singleton, raises
  `TypeError`. Never let a binding be silently ignored.
- `@Injector.override(Iface, on=predicate)` calls `on()` once at decoration time; if false, the
  class is validated as usual but returned unchanged and not bound. `on` must be callable.
- Callers can override an injected argument by passing it explicitly as a keyword argument.
- `Container` subclasses must be decorated with `@Injector.singleton`. `@MyContainer.component`
  works both bare and called with metadata (`@MyContainer.component(...)`). `_get_components`
  yields component objects; full `ComponentRegistration`s live in `container.components`.
  Registrations are stored per container class (not on the instance), so registering doesn't create
  the container; `_on_component_register` is replayed for earlier registrations when it is created.
  Lock order: the singleton creation lock may be held when taking the container lock, never the
  reverse. Never call user hooks while holding a library lock (snapshot under it, call after).
  `conftest.reset_injector` also resets the container module state.

## Conventions

- `requires-python` is `>=3.11`: don't use 3.12+ syntax (PEP 695 `class C[T]`, `def f[T]`) or
  3.12+/3.13+ stdlib APIs such as `warnings.deprecated`.
- Tests that register singletons or interfaces must use the `reset_injector` fixture from
  `conftest.py` (don't redefine it per file) so global state doesn't leak between tests. Define
  test singletons/containers inside the test function.
- Add tests for every behaviour change, in the matching `test_<module>.py`.
- Docstrings use reST-style `:param x:` / `:return:` fields; match the surrounding code.
- Keep the public API (`Injector`, `Provide`, `Container`, `ComponentRegistration`, `Collector`,
  `InterfaceFrozenError`, `InterfaceAlreadyBoundError`, `Injector.implements`,
  `Injector.override`) backwards compatible unless asked otherwise.
- When changing user-facing behaviour, update `README.md` and add an entry to `CHANGELOG.md`.
- Version is defined in two places that must match: `pyproject.toml` (`version`) and
  `src/smalldi/__init__.py` (`__version__`).
