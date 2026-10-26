# Swapping implementations

Depend on an interface, give it a default implementation, and swap the implementation with an override: at import time
for a platform or an environment, or inside a [context](../features/contexts.md) for one test. Callers keep asking
for the interface and never learn which class answered.

## Choosing a backend per environment

`@Injector.override(Interface, when=condition)` applies the override when `condition()` is true. The condition runs
once, when the decorator is applied, so it can read `sys.platform`, an environment variable or a settings file.

```python
import abc
import os

from smalldi import Injector, Provide

os.environ.setdefault("TREAT_DISPENSER", "auto")  # in a real program the environment is set outside


@Injector.interface
class TreatDispenser(abc.ABC):
    @abc.abstractmethod
    def dispense(self) -> str:
        pass


@Injector.implements(TreatDispenser)
@Injector.singleton
class HandFed(TreatDispenser):
    def dispense(self):
        return "a cookie from the hand"


@Injector.override(TreatDispenser, when=lambda: os.environ.get("TREAT_DISPENSER") == "auto")
@Injector.singleton
class AutoDispenser(TreatDispenser):
    def dispense(self):
        return "a cookie from the machine"


@Injector.inject
def treat(dispenser: Provide[TreatDispenser]):
    print(f"Pusheen gets {dispenser.dispense()}")


treat()  # Pusheen gets a cookie from the machine
print(Injector.get_instance(HandFed).dispense())  # a cookie from the hand: the default is still registered
```

With `TREAT_DISPENSER` set to anything else, the decorator does nothing, `AutoDispenser` stays a plain singleton and
`treat()` prints the hand-fed cookie. The default implementation stays registered either way, so code that asks for
`HandFed` by name still gets one.

## Extending a class you don't own

A singleton can be overridden by a subclass without an interface in between. Everything that asks for the original
class receives the subclass's instance, which is how an application customises a singleton defined in a library.

```python
from smalldi import Injector, Provide


@Injector.singleton
class NapSpot:  # defined in a library
    def describe(self):
        return "the sofa"


@Injector.override(NapSpot)  # defined in the application, before anything asks for a NapSpot
@Injector.singleton
class HeatedNapSpot(NapSpot):
    def describe(self):
        return f"{super().describe()}, warmed up"


@Injector.inject
def nap(spot: Provide[NapSpot]):
    print(f"Pusheen naps on {spot.describe()}")


nap()  # Pusheen naps on the sofa, warmed up
print(Injector.get_instance(NapSpot) is Injector.get_instance(HeatedNapSpot))  # True
```

## Getting the order right

* **Declare overrides before the first injection.** A target is frozen once an instance was requested through it,
  and a frozen target raises `SingletonFrozenError`. Put overrides in a module the entry point imports early, or in
  the package `__init__`, and never request instances at import time.
* **Something already injected at the root can still be swapped in a block.** Open `with Injector.context():` and
  declare the override inside: a `RESET` child starts unfrozen, and the override is gone when the block ends. This is
  the pattern for [tests](testing.md).
* **One override per target, no chains.** An override can't be overridden and an overridden singleton can't become an
  override. To put another override on top of one already in place, open a `STACK` context, where every override
  becomes the base of its singleton.
* **An interface override wins over the implementation whatever the import order**, so the default implementation
  may be declared in a module imported later than the override.

## Read on

* [Interfaces and overrides](../features/interfaces.md), the feature page
* [README: Overrides](../../README.md#overrides), every rule and what freezes a target
* [Concurrency](../concurrency.md), an override racing an injection in another thread
