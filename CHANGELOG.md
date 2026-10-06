# Changelog
## 0.3.0
* Singletons are now lazy: they are instantiated on first injection instead of on registration
* Singletons are frozen once an instance was requested and can't be overridden afterwards
* Deprecate `Injector.singletons_available` (planned removal in 1.0.0): reading it warns, returns a read-only snapshot
  and freezes all singletons; inject singletons instead of reading them
* Registering a singleton or an interface twice (e.g. after a module reload) raises `TypeError`
* Add `smalldi.concurrency` with `@synchronized` and `@threadsafe` decorators (async functions aren't supported yet)
* Add interfaces: `@Injector.interface` marks an abstract class as an interface, `@Injector.implements` binds it to a singleton,
  and `Provide[Interface]` injects the implementation
* Add `@Injector.override` to inject another singleton for an interface instead of its implementation, regardless of
  import order; an interface may have one override, declared before it is first injected
* `@Injector.override` can override singletons too; overrides are followed transitively
* Export `SingletonFrozenError` from `smalldi`
* Fix containers with lazy singletons

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release