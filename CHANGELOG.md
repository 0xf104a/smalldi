# Changelog
## 0.3.0
* Singletons are now lazy: they are instantiated on first injection instead of on registration
* Singletons are frozen once instantiated and can't be overridden afterwards
* Add `Injector.singletons`, a read-only mapping of singleton classes to their instances
* Deprecate `Injector.singletons_available` in favour of `Injector.singletons`; it is now read-only
* Registering a singleton twice (e.g. after a module reload) now emits a `RuntimeWarning`
* Add `smalldi.concurrency` with `@synchronized` and `@threadsafe` decorators (async functions aren't supported yet)
* Fix containers with lazy singletons

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release