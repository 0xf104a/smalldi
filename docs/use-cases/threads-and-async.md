# Threads and asyncio

The injector may be used from any number of threads. Each singleton is built once per context, threads asking for an
instance under construction wait for it, and no registry lock is held while a constructor runs. Contexts are tracked
per thread and per asyncio task, so a block opened in one thread doesn't change what another thread sees.

## Exactly one instance across threads

```python
import threading
import time

from smalldi import Injector, Provide


@Injector.singleton
class Kitchen:
    def __init__(self):
        time.sleep(0.05)  # a slow constructor
        print("the kitchen is ready")


@Injector.inject
def cook(kitchen: Provide[Kitchen]):
    return kitchen


kitchens = []
threads = [threading.Thread(target=lambda: kitchens.append(cook())) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(len({id(kitchen) for kitchen in kitchens}))  # 1: built once, the other threads waited for it
```

## Contexts and threads

A plain `threading.Thread` starts in the root context whatever its creator had open. `ContextAwareThread` captures
the creator's current context and runs its target inside it.

```python
import threading

from smalldi import Injector
from smalldi.thread import ContextAwareThread


@Injector.singleton
class Bowl:
    content = "kibble"


def report(label):
    print(f"{label}: Pusheen finds {Injector.get_instance(Bowl).content}")


with Injector.context():
    @Injector.override(Bowl)
    @Injector.singleton
    class TunaBowl(Bowl):
        content = "tuna"

    plain = threading.Thread(target=report, args=("plain thread",))
    aware = ContextAwareThread(target=report, args=("context-aware thread",))
    for thread in (plain, aware):
        thread.start()
        thread.join()
# plain thread: Pusheen finds kibble
# context-aware thread: Pusheen finds tuna
```

The captured context is the object itself, not a copy, so the thread shares the block's instances. Contexts the
target opens inside `run()` must be closed before the target returns; a thread ending with contexts still open gets
them removed with a `ResourceWarning`.

## Guarding a singleton's state

One instance shared by every thread means its mutable state is shared too. `@threadsafe` from `smalldi.concurrency`
locks per instance:

```python
import threading

from smalldi import Injector, Provide
from smalldi.concurrency import threadsafe


@Injector.singleton
class CookieJar:
    def __init__(self):
        self.cookies = 4000

    @threadsafe
    def take(self):
        left = self.cookies
        self.cookies = left - 1


@Injector.inject
def feast(jar: Provide[CookieJar]):
    for _ in range(1000):
        jar.take()


threads = [threading.Thread(target=feast) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(f"{Injector.get_instance(CookieJar).cookies} cookies left")  # 0 cookies left
```

## asyncio

`@Injector.inject` on an `async def` returns a coroutine function; its `Provide[T]` parameters are resolved when the
coroutine starts running, in the context of the task running it. A task starts in the root context, and opening
injection contexts inside coroutines isn't supported: set up overrides before the event loop runs.

```python
import asyncio

from smalldi import Injector, Provide


@Injector.singleton
class NapSpot:
    name = "the sofa"


@Injector.inject
async def nap(who, spot: Provide[NapSpot]):
    await asyncio.sleep(0)
    return f"{who} naps on {spot.name}"


async def main():
    print(await asyncio.gather(nap("Pusheen"), nap("Stormy"), nap("Pip")))


asyncio.run(main())
```

## Known limitation

A dependency cycle within one thread raises `RuntimeError`. A cycle that spans several threads, or a constructor that
waits for another thread which needs the singleton being constructed, isn't detected and deadlocks. Keep constructors
free of `join`, `Event.wait` and `Future.result` on threads that use the injector.

## Read on

* [Concurrency](../concurrency.md), the locking model, freeze-on-lookup and override refusals
* [Contexts in depth](../contexts.md), the per-thread and per-task context stacks with diagrams
* [Utilities](../features/utilities.md), `@synchronized`, `@threadsafe` and their limitations
