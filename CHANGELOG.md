# Changelog
## 0.3.0
* Add interface bindings: `@Injector.implements(Interface)` makes `Provide[Interface]` inject the bound singleton
* Add `@Injector.override(Interface)` to replace the baseline implementation of an interface once,
  optionally only when `on` predicate returns true
* Add `InterfaceAlreadyBoundError`, raised when binding a second baseline or a second override
* Add `InterfaceFrozenError`, raised when changing the implementation of an interface which was already injected
* Deprecate `Injector.singletons_available`
* Allow injecting singletons into container components

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release