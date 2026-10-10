# Changelog
## 0.3.0
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