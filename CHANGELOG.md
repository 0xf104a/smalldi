# Changelog
## 0.3.0
* Add interface bindings: `@Injector.implements(Interface)` makes `Provide[Interface]` inject the bound singleton
* Add `InterfaceFrozenError`, raised when rebinding an interface which was already injected
* Deprecate `Injector.singletons_available`
* Allow injecting singletons into container components

## 0.2.0
* Add container support

## 0.1.1
* Update docs embedded in README
* Some imports optimization in tests

## 0.1.0
* Initial release