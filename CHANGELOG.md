# Changelog
## 0.5.0
### Added
* `smalldi.context.InjectionContextSingletonOverride`, a dataclass base declaring a `SHALLOW` child context field by
  field. `Injector.context` accepts the subclass, with the fields' defaults as the values, or an instance of it, with
  its attributes as the values, besides an `InjectionSubcontextType` member as before; `apply(context)` on the class or
  the instance derives the child of a given context without pushing it. A field `n: T` gives the block a singleton of
  its own for `T`: a clone of the singleton of a registered `T`, or a registration in the block only for an
  unregistered `T`; a default value becomes that singleton's instance. A field may not declare an abstract class. A
  default that is a plain value other than None is one object preset in every context derived from the class, which
  warns with `UserWarning` once per class; `dataclasses.field(default_factory=...)` makes a new one per context. A
  subclass of a decorated subclass must be decorated with `@dataclasses.dataclass` itself, else `TypeError`
* `smalldi.decorator.oneshot` and `smalldi.decorator.OneshotLevel`: `@oneshot` marks a function to run once, every
  later call returning the first result. `OneshotLevel.GLOBAL`, the level of the bare `@oneshot` and of `@oneshot()`,
  runs it once everywhere; `@oneshot(OneshotLevel.PER_CLASS)` once per class, the `cls` of a classmethod or
  `type(self)` of an instance method; `@oneshot(OneshotLevel.PER_INSTANCE)` once per instance, on instance methods
  only. On a classmethod or a staticmethod `@oneshot` goes above `@classmethod` / `@staticmethod`. A call that raises
  stores nothing, a re-entrant call for the same key while the first call runs raises `RuntimeError`, and concurrent
  first calls run the function once, the other callers waiting for its result
* `LazySingleton.set_instance(instance)`, which binds a ready-made instance and freezes the singleton
* A documentation site on Read the Docs: `zensical.toml`, `.readthedocs.yaml` and `.github/scripts/stage_docs.py`
  build README.md, `docs/`, CHANGELOG.md, llms.txt and a mkdocstrings API reference with Zensical, styled by the
  Material 3 stylesheet `docs/assets/material3.css`; the CI docs job builds the site in strict mode. The site
  version `latest` documents the latest release: `.github/scripts/checkout_latest_release.sh` checks out the highest
  release tag before the build, and the publish workflow triggers the rebuild of `latest` on a release

### Fixed
* The README interfaces example exits with status 0 whether or not Ootani is on patrol: Cohee-Neko stops buying when
  Kansai-Neko's stock runs out instead of the example exiting with status 1, which failed the docs check outside
  22:00-06:00 UTC

## 0.4.0
Migration guides: [0.3 → 0.4](docs/migration/0.3-to-0.4.md), [0.2 → 0.4](docs/migration/0.2-to-0.4.md)
### Added
* Injection contexts: `with Injector.context(kind):` runs a block in a child context derived from the current one, so
  registrations, overrides and instances made inside the block are scoped to it; `__enter__` builds the child and
  returns the `InjectionContext`, `__exit__` pops exactly the context it pushed, exiting out of order or entering the
  same manager twice raises `RuntimeError`
* The five context kinds, members of `smalldi.context.InjectionSubcontextType`: `PRESERVE` (the current context
  itself), `RESET` (same registrations, implementations and overrides, every singleton a fresh unfrozen one without an
  instance; the default), `EMPTY` (nothing registered), `SHALLOW` (a new registry sharing the same `LazySingleton`
  objects, so instances and frozen state are shared and an override of an inherited singleton is visible in the
  parent) and `STACK` (every effective class becomes a fresh base without override, an interface's override becomes
  its implementation, so both can be overridden again)
* `Injector.context(kind)`, `Injector.foreign_context(ctx)`, which pushes a given `InjectionContext` as is, and
  `Injector.get_context()`, which returns the current context
* Per-slice context tracking: contexts are kept per execution slice, the running `asyncio.Task` or else the current
  `threading.Thread`; a slice with nothing pushed sees the root context, and a new thread or Task starts in the root
  context whatever its creator had open
* `smalldi.thread.ContextAwareThread`, a `threading.Thread` that captures its creator's current context in `__init__`
  and enters it for the duration of `run()`
* A slice that finishes with injection contexts still open has them removed and emits a `ResourceWarning`

### Changed
* `@Injector.inject` on an `async def` function now returns a coroutine function and resolves its dependencies when
  the coroutine starts running instead of when the function is called

### Fixed
* An instance request and the freezing of what it looks up are one step under the injector's lock: an override that
  races a request for its target or for the overriding class is refused with `SingletonFrozenError` instead of
  succeeding after the request was made, and no constructor runs inside a `LazySingleton` the override discarded
* `@Injector.override(Target)` raises `SingletonFrozenError` when the overriding class was requested but has no
  instance, because its constructor is still running or failed; before, the override succeeded and the constructor
  ran a second time. An overriding class whose instance exists shares it with the target, as before

## 0.3.0
Migration guide: [0.2 → 0.3](docs/migration/0.2-to-0.3.md)
### Breaking changes
* `@Injector.singleton` no longer instantiates the class when it is applied: the instance is created on first use, at
  most once, so constructor side effects at import time are gone; where you relied on construction at registration,
  inject the singleton or call `Injector.get_instance`
* `Injector.singletons_available` is a read-only snapshot instead of a plain dict: assigning to it raises `TypeError`;
  register singletons with `@Injector.singleton` and swap them with `@Injector.override` instead of writing to it
* `@Injector.singleton` raises `TypeError` for a class that is already registered instead of replacing its instance:
  register each class once. A reloaded module defines new class objects, which are registered as additional singletons
  next to the old ones without an error; module reloading isn't supported
* `@Injector.inject` resolves `Provide[T]` at every call instead of capturing instances when the function is decorated:
  an override declared after decoration and before the first call is respected, and the instance is created by the
  first call; `T` must still be registered at decoration, otherwise `TypeError` is raised

### Added
* `@Injector.interface` registers an abstract class as an interface, `@Injector.implements(Interface)` (applied above
  `@Injector.singleton`) declares its one implementation, and `Provide[Interface]` injects the implementation's instance;
  a second implementation raises `RuntimeError`, and calling an injected function while the interface has no binding
  raises `RuntimeError`
* `@Injector.override(Target)` (applied above `@Injector.singleton`) injects a registered singleton instead of another
  singleton or instead of an interface's implementation, whatever the import order; the target's class, or the
  implementation, is never instantiated through the injector
* Override validation, checked before anything is bound: the target must be a registered singleton or interface, the
  override a registered singleton and a subclass of the target, a class can't override itself, and each target has at
  most one override (a second one raises `RuntimeError` for a singleton target and `TypeError` for an interface target)
* Conditional overrides: `@Injector.override(Target, when=...)` applies only when `when()` returns `True`; `when` is
  called once, when the decorator is applied, and when it returns `False` the decorator binds nothing and leaves
  existing bindings unchanged
* Overrides are not transitive: an override can't be overridden and an overridden singleton can't become an override,
  both raise `TypeError`. An interface whose implementation is overridden resolves to the implementation's override,
  which is a single delegation hop, not a chain
* Freezing: a singleton or interface is frozen once an instance was requested through it, even if construction failed,
  and overriding it afterwards raises `SingletonFrozenError`, exported from `smalldi`; declare overrides before the first
  injection of their targets
* `Injector.get_instance(T)` returns the instance for a registered singleton or interface, creating it if needed;
  `Injector.is_singleton(cls)` and `Injector.is_interface(cls)` tell how a class is registered
* `smalldi.concurrency` with the `@synchronized` and `@threadsafe` decorators (async functions aren't supported yet and
  raise `NotImplementedError`)
* `smalldi.decorator` with `staticclass`; `smalldi.wrappers` is kept as an alias and keeps working
* `smalldi.atomic.AtomicSet`, a set whose operations are serialized by a lock
* Thread safety: `Injector` may be used from several threads, each singleton is constructed at most once, and a binding
  racing the first injection of its target either wins or is refused with `SingletonFrozenError`. Known limitation: a
  dependency cycle spanning several threads, or a constructor waiting for a thread that needs the singleton being
  constructed, isn't detected and may deadlock; cycles within one thread raise `RuntimeError`

### Changed
* `typing-extensions` is no longer a dependency: smalldi has zero runtime dependencies; add it to your own
  dependencies if you relied on smalldi to install it
* `Container` creates its instance through `Injector.get_instance` when the first component is registered, which
  freezes it: override a container before registering components, and components registered in an overridden container
  go to the override's instance
* Every public module, class and method has a docstring describing its behaviour and exceptions

### Deprecated
* `Injector.singletons_available` (removal planned in 1.0.0): every read emits a `DeprecationWarning`, instantiates and
  freezes every registered singleton, and returns a read-only snapshot without interfaces; inject singletons with
  `Provide[T]` or call `Injector.get_instance` instead

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release