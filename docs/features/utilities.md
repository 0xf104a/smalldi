# Utilities

Three helpers ship with the injector: the lock decorators of `smalldi.concurrency`, `oneshot` from
`smalldi.decorator`, and `Collector`, which imports a package so its decorators run.

## Lock decorators

`@synchronized` guards a function with one reentrant lock shared by every caller. `@threadsafe` picks the lock from
where the method is defined: per instance for instance methods, per class for classmethods, per function for
staticmethods.

```python
import threading

from smalldi import Injector, Provide
from smalldi.concurrency import threadsafe


@Injector.singleton
class CookieCounter:
    def __init__(self):
        self.eaten = 0

    @threadsafe  # one lock per CookieCounter instance
    def eat(self):
        eaten = self.eaten
        self.eaten = eaten + 1


@Injector.inject
def feast(counter: Provide[CookieCounter]):
    for _ in range(1000):
        counter.eat()


threads = [threading.Thread(target=feast) for _ in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(f"Pusheen ate {Injector.get_instance(CookieCounter).eaten} cookies")  # Pusheen ate 4000 cookies
```

Neither decorator supports `async def` (`NotImplementedError`), and on a generator function the lock is held only
while the generator object is created. `@threadsafe` stores the instance lock in the object's `__dict__`, so classes
with `__slots__` must list `__instance_mutex__`, and an object holding a lock can't be pickled; the
[README](../../README.md#limitations) shows the `__getstate__` that drops it.

## Oneshot

`@oneshot` runs a function once and returns the first result on every later call. `OneshotLevel.GLOBAL`, the level
of the bare decorator, is once everywhere; `PER_CLASS` is once per class and `PER_INSTANCE` once per instance.

```python
from smalldi.decorator import oneshot, OneshotLevel


class Cat:
    def __init__(self, name):
        self.name = name

    @oneshot(OneshotLevel.PER_INSTANCE)
    def favourite_nap_spot(self):
        print(f"{self.name} looks around")
        return "the sofa" if self.name == "Pusheen" else "the windowsill"


pusheen, stormy = Cat("Pusheen"), Cat("Stormy")
print(pusheen.favourite_nap_spot())  # Pusheen looks around, then the sofa
print(pusheen.favourite_nap_spot())  # the sofa: decided already
print(stormy.favourite_nap_spot())   # Stormy looks around, then the windowsill
```

A call that raises stores nothing, a re-entrant call for the same key raises `RuntimeError`, and concurrent first
calls run the function once while the other callers wait. On a classmethod or staticmethod, `@oneshot` goes above
`@classmethod` or `@staticmethod`.

## Collector

Decorators run when their module is imported, so a module nobody imports registers nothing.
`Collector.collect_from_package(name)` imports a package and every module and subpackage under it, in
`pkgutil.walk_packages` order. Call it once at startup, from a top-level module, before anything is injected; calling
it from a module that the collected modules import themselves leads to circular imports.

```python title="main.py"
from smalldi.collector import Collector

Collector.collect_from_package("treats.plugins")  # every @Injector.singleton and @Menu.component in there has run
```

The [plugins use case](../use-cases/plugins.md) has a complete program around it.

## Read on

* [README: Utilities](../../README.md#utilities), the limitations of the lock decorators and the `oneshot` rules
* The API reference of the site, `smalldi.concurrency`, `smalldi.decorator` and `smalldi.collector`
