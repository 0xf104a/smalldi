# Features

smalldi is built around four features, singletons, interfaces with overrides, contexts and containers, plus a few
utilities. Each page here states what the feature does, shows it on a short example that runs as-is, lists what to
know about it, and points to the full rules in the [README](../../README.md) and to the use cases built on it.

| Feature                                  | What you get                                                                   | Reach for it when                                                                                   |
|------------------------------------------|--------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| [Singletons](singletons.md)              | One lazily built instance per class, passed to every `Provide[T]` parameter    | Services depend on other services and you don't want to hand them around yourself                   |
| [Interfaces and overrides](interfaces.md) | Code depends on an abstract class; what is injected for it can be swapped      | Callers shouldn't know which backend they talk to, or the backend differs per platform or environment |
| [Contexts](contexts.md)                  | A `with` block whose registrations, overrides and instances stay in the block  | Tests need fresh instances or fakes that don't leak into each other                                 |
| [Containers](containers.md)              | A singleton that collects the classes and functions decorated as its components | Plugins, handlers or commands register themselves and something iterates over them                  |
| [Utilities](utilities.md)                | `@synchronized`, `@threadsafe`, `@oneshot` and `Collector`                     | Guarding state shared between threads, running setup once, importing a package so its decorators run |

If you know what you want to achieve rather than which feature does it, start from the
[use cases](../use-cases/index.md) instead.
