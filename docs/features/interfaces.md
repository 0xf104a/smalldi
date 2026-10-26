# Interfaces and overrides

An interface is an abstract class registered with `@Injector.interface`; one singleton implements it with
`@Injector.implements(Interface)`, and `Provide[Interface]` receives that singleton's instance. An override,
`@Injector.override(Target)`, makes another singleton injected instead of an interface's implementation or instead of
another singleton.

## Example

```python
import abc

from smalldi import Injector, Provide, SingletonFrozenError


@Injector.interface
class TreatShelf(abc.ABC):
    @abc.abstractmethod
    def treat(self) -> str:
        pass


@Injector.implements(TreatShelf)
@Injector.singleton
class CookieShelf(TreatShelf):
    def treat(self):
        return "cookie"


@Injector.inject
def snack_time(shelf: Provide[TreatShelf]):
    print(f"Pusheen gets a {shelf.treat()}")


# An override is injected instead of the implementation. It is declared before anything asks for the shelf.
@Injector.override(TreatShelf)
@Injector.singleton
class TunaShelf(TreatShelf):
    def treat(self):
        return "tuna"


snack_time()  # Pusheen gets a tuna
print(Injector.get_instance(TreatShelf) is Injector.get_instance(TunaShelf))  # True
print(Injector.get_instance(CookieShelf).treat())  # cookie: the implementation stays registered on its own


# Overriding a singleton works the same way, and a request freezes its target: a later override is refused.
@Injector.singleton
class NapSpot:
    name = "the sofa"


@Injector.inject
def nap(spot: Provide[NapSpot]):
    print(f"Pusheen naps on {spot.name}")


nap()  # Pusheen naps on the sofa; NapSpot is frozen now

try:
    @Injector.override(NapSpot)
    @Injector.singleton
    class Blanket(NapSpot):
        name = "the blanket"
except SingletonFrozenError as e:
    print(type(e).__name__)  # SingletonFrozenError
```

## What to know

* An interface is an `abc.ABC` subclass with at least one abstract method. It has at most one implementation,
  declared with `@Injector.implements(Interface)` *above* `@Injector.singleton`; the singleton must subclass the
  interface. `Provide[Interface]` and `Provide[Implementation]` receive one object.
* A function may be decorated with `@Injector.inject` before the interface has an implementation; it only needs one
  by the time it is called, else `RuntimeError`.
* `@Injector.override(Target)` goes *above* `@Injector.singleton` too. `Target` is an interface or a singleton, and
  the overriding class must subclass it. An overridden singleton is never instantiated by the injector; an interface
  override wins whether it is declared before or after the implementation.
* `@Injector.override(Target, when=condition)` applies the override only if `condition()` is true. The condition is
  evaluated once, when the decorator runs, which is how a platform-specific or environment-specific implementation is
  chosen at import time.
* Each target has one override, and overrides don't chain: an override can't be overridden, and an overridden
  singleton can't become an override.
* A target is frozen once an instance was requested through it, even if the request failed. A frozen target raises
  `SingletonFrozenError` on `@Injector.override`. Declare overrides before anything injects their targets, or inside
  a `RESET` or `STACK` [context](contexts.md), where every singleton and interface starts unfrozen.
* `from smalldi import interface, implements, override` are shorthands for the `Injector` decorators;
  `SingletonFrozenError` is exported by `smalldi` as well.

## Read on

* [README: Interfaces](../../README.md#interfaces) and [README: Overrides](../../README.md#overrides), the full rules
  and the freezing rules in detail
* [Use case: swapping implementations](../use-cases/swapping-implementations.md)
* [Use case: testing](../use-cases/testing.md), fakes scoped to one test
* [Concurrency](../concurrency.md), what an override racing an injection does
