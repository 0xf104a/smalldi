# Use cases

Each page here starts from something you want to do, shows a complete program doing it with smalldi, and explains the
choices along the way. Every example runs as-is.

| You want to                                                              | Page                                                       | Features involved                                                                         |
|--------------------------------------------------------------------------|------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| Wire services together without passing them around by hand               | [Wiring an application](wiring-an-application.md)          | [Singletons](../features/singletons.md)                                                   |
| Choose a backend per platform or environment, or extend a class you don't own | [Swapping implementations](swapping-implementations.md) | [Interfaces and overrides](../features/interfaces.md)                                     |
| Give every test fresh instances, fakes and mocks that don't leak         | [Testing](testing.md)                                      | [Contexts](../features/contexts.md), [overrides](../features/interfaces.md)               |
| Let plugins, handlers or commands register themselves across a package   | [Plugins and registries](plugins.md)                       | [Containers](../features/containers.md), [`Collector`](../features/utilities.md#collector) |
| Use the injector from several threads and from asyncio                   | [Threads and asyncio](threads-and-async.md)                | [Contexts](../features/contexts.md), [lock decorators](../features/utilities.md)          |

The [features](../features/index.md) pages describe each building block on its own, and the
[README](../../README.md) has the complete rules.
