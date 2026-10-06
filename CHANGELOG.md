# Changelog
## 0.3.0
* Add interface bindings: `@Injector.implements(Interface)` makes `Provide[Interface]` inject the bound singleton
* Add `@Injector.override(Interface)` to replace the baseline implementation of an interface once,
  optionally only when `on` predicate returns true
* Add `InterfaceAlreadyBoundError`, raised when binding a second baseline or a second override
* Add `InterfaceFrozenError`, raised when changing the implementation of an interface which was already injected
* `@Injector.override` validates the override even when its `on` predicate returns false
* `@Injector.implements` and `@Injector.override` raise `TypeError` when the interface is itself a singleton,
  and `@Injector.singleton` raises `TypeError` on a class already used as an interface
  (previously such bindings were silently ignored)
* Decorating a class with `@Injector.singleton` twice raises `ValueError` instead of creating a second instance
* **Breaking:** singletons are created lazily on first injection instead of at decoration time:
  `__init__` side effects and errors move from import time to first use
* **Breaking:** `@Injector.inject` resolves dependencies on the first call instead of at decoration time,
  so declaration order no longer matters; missing dependencies raise `TypeError` on call.
  Interfaces freeze on the first call of a function injecting them, so whether a late binding raises
  `InterfaceFrozenError` depends on whether that function was already called
* Circular dependencies between singletons raise `TypeError`, also when threads create them concurrently
* Registering a component doesn't create the container; earlier registrations are passed to
  `_on_component_register` when the container is created. Containers also get components of the
  container classes they inherit from. `Container.components` is a read-only property
* Add `smalldi.concurrency` with `@threadsafe`, `@threadsafe_fn` and `@threadsafe_cls`
* Deprecate `Injector.singletons_available`. **Breaking:** it is a read-only snapshot of singletons which were
  already created (singletons not injected yet are missing), and assigning to it raises `AttributeError`
* Allow injecting singletons into container components

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release