# Wiring an application

Register each service as a singleton, declare what it needs with `Provide[T]` parameters, and let the injector build
the graph on first use. Nothing is constructed at import time, so the order in which modules load doesn't matter, and
no module has to know how to assemble another.

## Example

```python
import sys

from smalldi import Provide, inject, singleton


@singleton
class Settings:
    def __init__(self):
        self.cat = "Pusheen"
        self.snacks_per_day = 2


@singleton
class SnackStore:
    @inject
    def __init__(self, settings: Provide[Settings]):
        print(f"stocking the store for {settings.cat}")
        self.shelf = ["cookie", "tuna", "cookie"]

    def take(self):
        return self.shelf.pop(0)


@singleton
class FeedingService:
    @inject
    def __init__(self, settings: Provide[Settings], store: Provide[SnackStore]):
        self.settings = settings
        self.store = store

    def feed(self):
        return [self.store.take() for _ in range(self.settings.snacks_per_day)]


@inject
def main(service: Provide[FeedingService], settings: Provide[Settings]) -> int:
    print(f"{settings.cat} eats {' and '.join(service.feed())}")
    return 0


if __name__ == "__main__":
    print("starting")  # nothing has been built yet
    sys.exit(main())   # stocking the store for Pusheen, then: Pusheen eats cookie and tuna
```

## How it fits together

**Construction happens on demand.** Calling `main()` asks for `FeedingService`, whose constructor asks for `Settings`
and `SnackStore`, whose constructor asks for `Settings` again and gets the same instance. Each class is built once,
in dependency order, the first time it is needed. A class that needs itself through its dependencies raises
`RuntimeError` instead of recursing.

**Dependencies are declared, not passed.** `main` takes `Provide[FeedingService]` and gets it without anyone
constructing a `FeedingService` and handing it over. Adding a dependency to a service means adding a parameter to its
constructor; its callers don't change.

**The entry point is an injected function.** `@inject` on `main` makes the program's root a plain function call.
Where a framework calls your code with its own arguments, such as a request handler, `Injector.get_instance(T)`
fetches an instance from code that isn't injected itself.

**A caller can still pass a dependency.** `main(settings=Settings())` replaces the injected value for that call, as a
keyword argument only. That is the lightest way to hand a stand-in to one function; for a whole test, see
[testing](testing.md).

**Modules register when they are imported.** A singleton defined in a module nobody imports isn't registered, and
`Provide[T]` naming an unregistered class raises `TypeError` where the function is decorated. Import the modules that
define your singletons from the entry point, or let [`Collector.collect_from_package`](plugins.md) import a whole
package. Do it at the root of the program, not inside a `with Injector.context(...)` block, because a module imported
inside a context keeps its registrations in that context.

**Async entry points work the same way.** `@inject` on an `async def` returns a coroutine function whose `Provide[T]`
parameters are resolved when the coroutine starts running:

```python
import asyncio

from smalldi import Provide, inject, singleton


@singleton
class NapSpot:
    name = "the sofa"


@inject
async def nap(who, spot: Provide[NapSpot]):
    await asyncio.sleep(0)
    return f"{who} naps on {spot.name}"


async def main():
    print(await asyncio.gather(nap("Pusheen"), nap("Stormy")))  # both nap on the sofa


asyncio.run(main())
```

## Read on

* [Singletons](../features/singletons.md), the feature page
* [README: How singletons work](../../README.md#how-singletons-work), lazy construction, freezing and the module
  reload warning
* [Threads and asyncio](threads-and-async.md), when the services are used from several threads or tasks
