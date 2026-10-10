# smalldi: notes for coding agents

smalldi is an annotation-driven dependency-injection library for Python (>=3.11) with zero runtime dependencies.
The package lives in `src/smalldi/`, the tests in `src/tests/`.

## Module layout

- `src/smalldi/__init__.py`: `Injector` (the static registry and its decorators `singleton`, `interface`, `implements`, `override`, `inject`), `Injector.get_instance`, `Injector.is_singleton`, `Injector.is_interface`, the deprecated `Injector.singletons_available` descriptor, and the public re-exports `Provide` and `SingletonFrozenError`.
- `src/smalldi/_singleton.py`: `LazySingleton`, the lazily built single instance of a registered class, with delegation to an override, freezing and the circular-dependency check; `SingletonFrozenError`.
- `src/smalldi/_interfaces.py`: `InterfaceResolver`, the registry of interfaces, and `_LazyInterfaceImpl`, one interface's binding to the `LazySingleton` objects implementing and overriding it.
- `src/smalldi/annotation.py`: `Provide[T]` (an `Annotated` alias) and the helpers that read it from a function signature.
- `src/smalldi/container.py`: `Container`, a singleton base class collecting components registered with `@MyContainer.component`, and `ComponentRegistration`.
- `src/smalldi/collector.py`: `Collector.collect_from_package`, which imports every module of a package so its decorators run.
- `src/smalldi/concurrency.py`: `@synchronized`, `@threadsafe` and the `mutex` decorator factory, the reentrant-lock helpers used throughout the package.
- `src/smalldi/decorator.py`: `staticclass`, which makes a class uninstantiable.
- `src/smalldi/atomic.py`: `AtomicSet`, a lock-guarded set used by `LazySingleton` to track the threads inside a constructor.
- `src/smalldi/wrappers.py`: compatibility alias re-exporting `staticclass` from `smalldi.decorator`.
- `src/smalldi/py.typed`: marker that the package is typed.

## Running the tests

```shell
cd src && python -m pytest
```

Tests need no installation beyond pytest: `src/` is the import root. `src/tests/README.md` lists what each test module covers.

## Design invariants

- There is exactly one `LazySingleton` per registered class, owned by `Injector._singletons_available`. Interface bindings (`_LazyInterfaceImpl`) refer to those objects and never create their own.
- Overrides are not transitive. No code follows chains of bindings or walks graphs: there is no recursive graph traversal and no cycle-detection walk. Resolution is at most one interface lookup followed by at most one delegation hop.
- Validation happens before mutation: every check of a binding or registration runs before anything changes, so a failed call leaves the registry and every binding as they were.
- Frozen means frozen. A singleton is frozen the first time its instance is requested, an interface the first time an instance is requested through it, even if that request failed. Nothing unfreezes a target; a frozen target accepts no override, and an interface accepts an implementation after freezing only if it already has an override.
- Decorator order: `@Injector.override(...)` and `@Injector.implements(...)` go above `@Injector.singleton`, because both require the decorated class to be a registered singleton already.
- No lock that guards the registry (`Injector.__class_mutex__`, the resolver lock) or a binding (a `LazySingleton` or `_LazyInterfaceImpl` state lock) is held while a constructor runs or while another instance is requested. Only the singleton's own build lock is held during construction.

## Known threading limitation

Circular dependencies are detected within one thread and raise `RuntimeError`. Two cases are not detected and may deadlock: a dependency cycle that spans several threads, and a constructor that waits (`join`, `Event.wait`, `Future.result`, ...) for another thread which needs the singleton being constructed, directly or through its dependencies. `test_cross_thread_circular_dependency_does_not_deadlock` in `src/tests/test_injector_concurrency.py` is skipped for this reason. Opt-in detection is planned; don't add graph walks to the resolution path to get it.

## House rules

- Zero runtime dependencies. `dependencies = []` in `pyproject.toml` stays empty; the standard library is enough.
- Deprecate before removing public API. A deprecated name keeps working and warns with `DeprecationWarning`; removal happens no earlier than 1.0.0.
- Tests use the public API only. The three specification files define the semantics: `src/tests/test_override_rules.py`, `src/tests/test_interface_bindings.py` and `src/tests/test_injector_concurrency.py`. Where the library disagrees with them, the library is what changes.
- Docs describe current behaviour only. README, `llms.txt` and this file contain no development history (no "now", "no longer", "used to", "previously"); history lives in `CHANGELOG.md`.
- README examples start with one plain technical sentence stating the concept, then the story example, then a `Rules:` list in plain technical language with no story in it. Every example runs as-is; error cases are `try/except` blocks printing the caught exception type.
- Cast for README examples: Pusheen (a chubby grey tabby who loves snacks, cookies and naps; siblings Stormy and Pip) 