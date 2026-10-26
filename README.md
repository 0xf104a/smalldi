# Small DI
[![PyPI](https://img.shields.io/pypi/v/smalldi)](https://pypi.org/project/smalldi/)
[![Python versions](https://img.shields.io/pypi/pyversions/smalldi)](https://pypi.org/project/smalldi/)
[![CI](https://github.com/0xf104a/smalldi/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/0xf104a/smalldi/actions/workflows/ci.yml)
[![Free-threading](https://img.shields.io/badge/free--threading-3.14t%20%7C%203.15t-blue)](https://py-free-threading.github.io/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/0xf104a/smalldi/blob/master/pyproject.toml)
[![License](https://img.shields.io/pypi/l/smalldi)](https://github.com/0xf104a/smalldi/blob/master/LICENSE)


The smallest dependency injection mechanism possible in python.
SmallDI provides you with an intuitive and simple interface for doing dependency
injections in your project.

SmallDI is built around four features: [singletons](#singletons), [containers](#containers),
[interfaces](#interfaces) and [contexts](#contexts).

# Singletons
A singleton is a class with exactly one instance, created on first use and passed to every function that
asks for it with `Provide[T]`.

## Example
<details>
<summary>Meowing and purring services</summary>

```python
import random

from smalldi import Injector, Provide

# Lets create some service
@Injector.singleton
class MeowService:
    _MEOWS = ["Meow", "Meow-meow", "Meowwwwww", "Mrromeowww", "Meeeeoooow"]
    def __init__(self):
        print("Meow-meow! Meowing service is initialized")
    
    def meow(self):
        print(random.choice(self._MEOWS))

# Now lets make purring service.
# But cats do not purr without telling meow!(at least in this test)
# So its time to inject dependency
@Injector.singleton
class PurrService:
    _PURRS = ["Purrrrr", "Purr-purr"]
    
    @Injector.inject
    def __init__(self, meow_service: Provide[MeowService]):
        self.meow_service = meow_service
        print("Purr-purr! Purring service is initialized")

    def purr(self):
        self.meow_service.meow()
        print(random.choice(self._PURRS))

# Now lets put it all together. 
# Ask our services to meow and then purr
@Injector.inject
def main(meow_service: Provide[MeowService], purr_service: Provide[PurrService]):
    meow_service.meow()
    purr_service.purr()

if __name__ == '__main__':
    main()
```

</details>

## Injector
Injector is a static class(i.e., one that should never be instantiated) which is the main (and currently the only)
DI container inside the library. Injector provides these decorators:

* `@Injector.singleton` registers a class whose instance may further be injected in functions
* `@Injector.interface` marks an abstract class as an [interface](#interfaces) singletons may implement
* `@Injector.implements(...)` declares which interface a singleton implements
* `@Injector.override(...)` makes a singleton injected instead of an interface's implementation or another singleton
* `@Injector.inject` replaces parameters annotated with type `Provide[Singleton]` (or `Provide[Interface]`) with actual
  instances of Singleton. Every `Provide[]` dependency must already be registered when the function is decorated,
  otherwise `TypeError` is raised.

Besides the decorators, `Injector.get_instance(T)` returns the instance for a registered singleton or interface,
creating it if needed, and `Injector.context(kind)` opens a [context](#contexts) in which registrations, overrides and
instances are scoped to a `with` block. `Injector.is_singleton(cls)` and `Injector.is_interface(cls)` tell how a class
is registered in the current context. The `smalldi` module exports `singleton`, `interface`, `implements`, `override`
and `inject` as shorthands for `Injector.singleton`, `Injector.interface`, `Injector.implements`, `Injector.override`
and `Injector.inject`, and `issingleton` and `isinterface` as shorthands for `Injector.is_singleton` and
`Injector.is_interface`, so `from smalldi import singleton` and `@singleton` work like `@Injector.singleton`.

## How singletons work
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes, and interfaces they implement, may be injected at the current state of library development.
Abstract classes can't be singletons.

Singletons are lazy: registering a class doesn't instantiate it. The instance is created, exactly once and in a
thread-safe way, the first time it is needed, that is when an `@Injector.inject`-decorated function is called or
`Injector.get_instance` is called. The instance belongs to the [context](#contexts) that is current at that moment:
a `RESET` context gets its own instances, created again on first use inside it.
Once an instance was requested, a singleton is *frozen* and can no longer be [overridden](#overrides), even if
creating the instance failed.

A singleton whose constructor requires itself, directly or through its dependencies, raises `RuntimeError`
(circular dependency). Cycles that span several threads, or a constructor waiting for a thread that needs the
singleton being constructed, deadlock instead and aren't detected.

> [!WARNING]
> Every class is registered once per [context](#contexts): registering the same class twice in one context raises
> `TypeError`. A reloaded module
> (`importlib.reload`) defines new class objects, which are registered as additional singletons next to the old
> ones without an error. DI is set up once per process; module reloading isn't supported.

## Provide
`Provide[T]` is an annotation for injector telling it that instead of this argument
instance of `T` should be passed. Caller of function with `Provide[T]` may explicitly
override argument annotated with `Provide[T]` by directly passing `annotated_di_arg=my_value`.
Only keyword arguments are recognized: passing the dependency positionally makes the call raise `TypeError`
for a duplicate argument.

`@Injector.inject` on an `async def` function returns a coroutine function. Its `Provide[T]` parameters are resolved
when the coroutine starts running, not when the function is called.

## `Injector.singletons_available` (deprecated)
Instances are meant to be reached through injection only. `Injector.singletons_available`, a read-only mapping of
every registered singleton class to its instance, is kept for compatibility and emits a `DeprecationWarning` when
read; it is planned to be removed in 1.0.0. Reading it creates every singleton that doesn't exist yet, so it freezes
the whole registry. Assigning to an item of the mapping raises `TypeError`.

# Containers
A container is a singleton that collects related classes or functions registered with `@MyContainer.component`.

## Example
<details>
<summary>Catnip flavours</summary>

```python
import sys
from abc import ABC, abstractmethod

from smalldi.container import Container
from smalldi import Injector, Provide

# Define interface for catnip
class Catnip(ABC):
    @property
    @abstractmethod
    def flavour(self):
        pass 

# Create a container to store different flavours of catnip
@Injector.singleton
class CatnipContainer(Container):
    def get_all_flavours(self) -> list[str]:
        flavours = list()
        for catnip in self._get_components():
            flavours.append(catnip().flavour)
        return flavours

@CatnipContainer.component
class PlainCatnip(Catnip):
    @property
    def flavour(self):
        return "plain"

@CatnipContainer.component
class ChocolateCatnip(Catnip):
    @property
    def flavour(self):
        return "chocolate"

@CatnipContainer.component
class StrawberryCatnip(Catnip):
    @property
    def flavour(self):
        return "strawberry"

@Injector.inject
def main(catnip_container: Provide[CatnipContainer]) -> int:
    print(catnip_container.get_all_flavours())
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

</details>

## How containers work
Container helps to collect classes and potential functions into a single unit.
All containers must be singletons inherited from `Container` class.
To create a container, write and inheritor of `Container` class and annotate it with `@Injector.singleton`.
Then you may register components in the container by annotating them with `@MyContainer.component`.
Additionally, `@MyContainer.component` may be called with `()` in order to provide metadata about the component.

Registering the first component creates the container instance, so a container can only be
[overridden](#overrides) before any component is registered in it. Components registered afterwards through
`@MyContainer.component` go to the overriding container's instance.

## `Container._get_components`
The container exposes protected method `_get_components` which returns an iterator over all classes and functions
registered in the container, in registration order. Their metadata is kept in [registrations](#componentregistration).

## `Container._on_component_register`
The container has protected method `_on_component_register(registration)` which is called with the
[registration](#componentregistration) every time a new component is registered in the container. Override it to react
to registrations; the default does nothing.

## ComponentRegistration
`ComponentRegistration` is a dataclass which holds information about registered component which
consists of:

* `component`: an actual component type
* `args`: arguments passed to `@MyContainer.component` during registration
* `kwargs`: keyword arguments passed to `@MyContainer.component` during registration

# Interfaces
An interface is an abstract class that code depends on instead of a concrete singleton; a singleton implements it,
and an override can replace that implementation without changing the code that injects it.

## Example
<details>
<summary>Cohee-Neko, Kansai-Neko and Ootani in disguise</summary>

```python
import abc
import dataclasses
import datetime
import enum
import random
import sys

from smalldi import Injector, Provide

def ootani_is_on_patrol() -> bool:
    # Otani tries to save his apartment complex as well as the world's strategic coffee reserves from Cohee-Neko
    # Though he is also very busy with mopping the yard and watering cabbages
    hour = datetime.datetime.now().hour
    return hour >= 22 or hour < 6 or random.random() < 0.1

class BeanKind(enum.Enum):
    REAL_BEAN = enum.auto()
    DECAF_BEAN = enum.auto()

@dataclasses.dataclass
class Bean:
    kind: BeanKind
    price: float

@Injector.interface
class CoffeeDealer(abc.ABC):
    @property
    @abc.abstractmethod
    def price(self) -> float:
        pass
    
    @abc.abstractmethod
    def buy(self, suggested_price: float) -> Bean:
        pass

# Kansai Neko doesn't care about apartment or coffee reserves
@Injector.implements(CoffeeDealer)
@Injector.singleton
class KansaiNekoCoffeeDealer(CoffeeDealer):
    def __init__(self):
        self.supply_remaining = 3401
        
    @property
    def price(self) -> float:
        return 1
    
    def buy(self, suggested_price: float) -> Bean:
        if self.supply_remaining == 0:
            raise ValueError("No more coffee. I've bean better.")
        if suggested_price - self.price >= 0:
            self.supply_remaining -= 1
            return Bean(BeanKind.REAL_BEAN, suggested_price)
        raise ValueError("No money, no ~~honey~~ coffee")

@Injector.override(CoffeeDealer, when=ootani_is_on_patrol)
@Injector.singleton
class OotaniDisguisedAsCoffeeDealer(CoffeeDealer):
    def __init__(self):
        self.supply_remaining = 3301
        
    @property
    def price(self) -> float:
        return 0.5

    def buy(self, suggested_price: float) -> Bean:
        if self.supply_remaining == 0:
            raise ValueError("No more coffee")
        if suggested_price - self.price >= 0:
            self.supply_remaining -= 1
            return Bean(BeanKind.DECAF_BEAN, suggested_price)
        raise ValueError("Oh...Cohee-Neko would be awake whole night again...")

# She starts doing anything after a "one more" cup of coffee
@Injector.singleton
class CoheeNeko:
    @Injector.inject
    def __init__(self, coffee_dealer: Provide[CoffeeDealer]):
        print("Fueeeelllling with CoFfEE")
        self.money = 0x29A01 # She spends THAT much on coffee?! What does she even do to get THIS amount of money?
        self.beans = 0
        while self.money > 0:
            try:
                bean = coffee_dealer.buy(1)
            except ValueError as e:
                # Kansai-Neko's stock runs out long before her money does
                print(f"{type(e).__name__}: {e}")
                break
            self.money -= 1
            if bean.kind is BeanKind.DECAF_BEAN:
                print("Ewww...Decaf...*throws away*")
                break
            self.beans += 1

@Injector.inject
def main(cohee_neko: Provide[CoheeNeko]) -> int:
    print("Cohee Neko is ready for next cup of coffee!")
    if cohee_neko.beans > 0:
        print(f"She has {cohee_neko.money}K Yens and drank Doppio++ from {cohee_neko.beans} beans already!")
    elif cohee_neko.beans == 0:
        print(f"She has {cohee_neko.money}K Yens and extremely strong desire to find next cup of coffee")
    else:
        print(f"WAD? Who gave her loan in COFFEE beans?")
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

</details>

## How interfaces work
An interface lets code depend on an abstraction instead of a concrete singleton. Mark the abstraction with
`@Injector.interface`, then declare the implementing singleton with `@Injector.implements`, applied *above*
`@Injector.singleton`:

<details>
<summary>Coffee machine with a caffeine computer</summary>

```python
import sys
import dataclasses
import abc
import enum

from smalldi import Injector, Provide


class CoffeeKind(enum.Enum):
    NORMAL = enum.auto()
    DECAF = enum.auto()


@Injector.interface
class CaffeineComputer(abc.ABC):
    @abc.abstractmethod
    def compute_caffeine(self, kind: CoffeeKind, amount_ml: float) -> float:
        """Computes the amount of caffeine in a given amount of coffee, assuming espresso benchmark."""
        pass

    @abc.abstractmethod
    def compute_volume_for_caffeine_dose(self, kind: CoffeeKind, target_caffeine_mg: float) -> float:
        """Computes the amount of coffee needed to reach a given caffeine dose."""
        pass


@Injector.implements(CaffeineComputer)
@Injector.singleton
class DefaultCaffeineComputer(CaffeineComputer):
    _ESPRESSO_CAFFEINE_MG_PER_ML = 2.0

    def compute_caffeine(self, kind: CoffeeKind, amount_ml: float) -> float:
        if kind is CoffeeKind.DECAF:
            return 0.0
        return self._ESPRESSO_CAFFEINE_MG_PER_ML * amount_ml

    def compute_volume_for_caffeine_dose(self, kind: CoffeeKind, target_caffeine_mg: float) -> float:
        if kind is CoffeeKind.DECAF:
            return 0.0
        return target_caffeine_mg / self._ESPRESSO_CAFFEINE_MG_PER_ML


@dataclasses.dataclass
class CoffeeCup:
    kind: CoffeeKind
    amount_ml: float
    caffeine_mg: float

    def __str__(self) -> str:
        return f"{self.kind.name} cup with {self.amount_ml} ml and {self.caffeine_mg} mg of caffeine"


@Injector.singleton
class CoffeeMachine:
    @Injector.inject
    def __init__(self, caffeine_computer: Provide[CaffeineComputer]):
        self._computer = caffeine_computer

    def brew(self, requested_coffee_kind: CoffeeKind, requested_caffeine_mg: float) -> CoffeeCup:
        if requested_caffeine_mg < 0:
            return CoffeeCup(requested_coffee_kind, 0, 0)  # Don't need caffeine? Why are you even near coffee machine?
        # Well it is definitely strange coffee machine, but aren't caffeine-addicted catgirls strange too?
        if requested_coffee_kind is CoffeeKind.DECAF:
            return CoffeeCup(requested_coffee_kind, 330, 0)  # You can drink decaf Espresso as water, can't you?
        computed_ml = self._computer.compute_volume_for_caffeine_dose(requested_coffee_kind, requested_caffeine_mg)
        # Who said computer is fair?
        computed_real_dose = self._computer.compute_caffeine(requested_coffee_kind, computed_ml)
        return CoffeeCup(requested_coffee_kind, computed_ml, computed_real_dose)


@Injector.inject
def main(machine: Provide[CoffeeMachine]) -> int:
    target_caffeine_amount = float(input("How many milligrams of caffeine do you want today? "))
    want_decaf = input("Do you want decaf? (y/n) ").lower().startswith('y')
    if want_decaf:
        coffee_kind = CoffeeKind.DECAF
    else:
        coffee_kind = CoffeeKind.NORMAL
    print("Here is your espresso cup:", machine.brew(coffee_kind, target_caffeine_amount))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as e:
        # Raised by a caffeine computer that refuses to serve the requested coffee
        print(f"{type(e).__name__}: {e}")
        sys.exit(1)
```

</details>

Rules:

* Each interface has at most one implementation; declaring a second one raises `RuntimeError`.
* `@Injector.implements` takes one interface. A singleton implementing several interfaces stacks the decorator,
  once per interface, above `@Injector.singleton`.
* The singleton must be a subclass of every interface it implements (virtual subclasses registered with
  `ABC.register` count).
* `Provide[Interface]` receives the same instance as `Provide[Implementation]`.
* A function may be decorated with `@Injector.inject` before the interface is implemented, as long as the interface
  itself is registered. Calling it while the interface has neither an implementation nor an override raises
  `RuntimeError`.
* Interfaces must be abstract classes (with at least one abstract method), so a class can't be both an interface and
  a singleton.
* Interfaces aren't listed in `Injector.singletons_available`, only their implementations are.
* Like singletons, an interface is registered once: registering the same class again raises `TypeError`. Repeating
  `@Injector.implements` raises `RuntimeError` like any second implementation, even with the same singleton.

## Overrides
Overrides apply to interfaces and to [singletons](#singletons) alike.

`@Injector.override` makes another singleton injected instead of an interface's implementation or instead of another
singleton, for example to swap in a fake in tests or a platform-specific implementation. Like `@Injector.implements`,
apply it above `@Injector.singleton`. An override declared inside a [context](#contexts) is gone once the context is
left, which is how a fake is scoped to one test.

Continuing the [coffee machine example](#how-interfaces-work), add these classes right before the
`if __name__ == '__main__':` block:

<details>
<summary>Cohee-Neko's caffeine computer and Ootani's coffee machine</summary>

```python
@Injector.override(CaffeineComputer)  # an interface
@Injector.singleton
class CoheeNekoXX71(CaffeineComputer):
    """An "improved" caffeine computer by Cohee Neko."""
    def compute_caffeine(self, kind: CoffeeKind, amount_ml: float) -> float:
        if kind is CoffeeKind.DECAF:
            raise ValueError("No one gets decaf!")
        return 2.0 * amount_ml

    def compute_volume_for_caffeine_dose(self, kind: CoffeeKind, target_caffeine_mg: float) -> float:
        if kind is CoffeeKind.DECAF:
            raise ValueError("No one gets decaf!")
        return target_caffeine_mg / 0.000001  # Sure, there is almost no caffeine in real coffee, this is why Cohee-Neko disabled decaf


@Injector.override(CoffeeMachine)  # a singleton
@Injector.singleton
class OotaniCoffeeMachine(CoffeeMachine):
    """A coffee machine by Ootani. No more caffeine in apartment complex."""
    def brew(self, requested_coffee_kind: CoffeeKind, requested_caffeine_mg: float) -> CoffeeCup:
        volume_ml = self._computer.compute_volume_for_caffeine_dose(requested_coffee_kind, requested_caffeine_mg)
        return CoffeeCup(CoffeeKind.DECAF, volume_ml, 0)
```

</details>

`Provide[CaffeineComputer]` then receives the `CoheeNekoXX71` instance and `Provide[CoffeeMachine]` the
`OotaniCoffeeMachine` instance: the same objects `Provide[CoheeNekoXX71]` and `Provide[OotaniCoffeeMachine]` receive.

An override may be conditional: `@Injector.override(what, when=condition)` takes a callable with no arguments.
`condition` is called once, when the decorator is applied, that is at import time. If it returns `False`, the
decorator does nothing and the class stays a plain singleton. The [Interfaces example](#interfaces) uses it to put
Ootani on patrol.

Rules:

* The overriding class must be a singleton and a subclass of its target; a class can't override itself.
  `@Injector.override` takes one target.
* An overridden singleton is never instantiated through the injector, and `Injector.singletons_available` maps it to its
  override's instance.
* An interface override wins whatever the import order: it may be declared before or after `@Injector.implements`, and
  an implementation declared later doesn't replace it. An interface with only an override is injectable too. The
  implementation stays registered, so `Provide[DefaultCaffeineComputer]` still receives a `DefaultCaffeineComputer`,
  unless `DefaultCaffeineComputer` is overridden as well. An interface whose implementation is overridden as a
  singleton resolves to that override.
* Overrides are not transitive: an override can't be overridden, and an overridden singleton can't become an
  override. Both raise `TypeError`.
* Each interface or singleton may have only one override, so it is unambiguous what gets injected: a second override
  of an interface raises `TypeError`, a second override of a singleton raises `RuntimeError`, even when it repeats the
  same class.
* Targets are *frozen* once an instance was requested through them, even if creating it failed, and overriding a
  frozen target raises `SingletonFrozenError`:
  * an interface the first time `Provide[Interface]` is resolved, or when `Injector.singletons_available` is read. Injecting
    the implementation class directly (`Provide[DefaultCaffeineComputer]`) doesn't freeze its interfaces;
  * a singleton once it is injected (directly, through an interface it implements, or through a singleton it
    overrides), when `Injector.singletons_available` is read, or, for containers, when the first component is registered.

  So declare overrides before anything injects their targets, or declare them inside a `RESET` or `STACK`
  [context](#contexts), whose singletons and interfaces start unfrozen. Frozen means frozen: nothing rebinds a frozen
  target, the only binding still accepted is the first `@Injector.implements` of an interface that already has an
  override, since the override keeps winning.
* A singleton target may be overridden by a class that was already injected: the target then shares that instance.
  If the overriding class was requested but has no instance, because its constructor is still running or raised,
  the override raises `SingletonFrozenError`.

`SingletonFrozenError` can be imported from `smalldi`.

# Contexts
A context is a registry of singletons and interfaces that a `with Injector.context(kind):` block makes current for
the code running inside it, so registrations, overrides and instances can be scoped to the block, for example to one
test.

## Example
<details>
<summary>Ryoga's bath</summary>

```python
import abc
import enum
import threading

from smalldi import Injector, Provide
from smalldi.context import InjectionSubcontextType
from smalldi.thread import ContextAwareThread


class Temperature(enum.Enum):
    COLD = enum.auto()
    HOT = enum.auto()


@Injector.interface
class Water(abc.ABC):
    @abc.abstractmethod
    def temperature(self) -> Temperature: ...

    @abc.abstractmethod
    def warm_up(self) -> None: ...


@Injector.implements(Water)
@Injector.singleton
class TapWater(Water):
    def __init__(self):
        self._temperature = Temperature.COLD

    def temperature(self) -> Temperature:
        return self._temperature

    def warm_up(self) -> None:
        self._temperature = Temperature.HOT


@Injector.singleton
class Ryoga:
    @Injector.inject
    def __init__(self, water: Provide[Water]):
        self._water = water

    def __str__(self) -> str:
        return "P-chan" if self._water.temperature() is Temperature.COLD else "Ryoga Hibiki"


@Injector.inject
def take_a_bath(water: Provide[Water]) -> None:
    water.warm_up()


@Injector.inject
def meet(ryoga: Provide[Ryoga]) -> str:
    return str(ryoga)


def meet_in_another_thread(thread_cls: type[threading.Thread]) -> str:
    seen = []
    thread = thread_cls(target=lambda: seen.append(meet()))
    thread.start()
    thread.join()
    return seen[0]


def main() -> None:
    print("Before the bath:", meet())                                    # P-chan

    # RESET keeps the blueprints (singletons, implementations, overrides)
    # but builds fresh instances: this bath warms up a different Water
    with Injector.context(InjectionSubcontextType.RESET):
        take_a_bath()
        print("In the bath:", meet())                                    # Ryoga Hibiki
        print("Akane, invited along:", meet_in_another_thread(ContextAwareThread))  # Ryoga Hibiki
        print("Ranma, outside the door:", meet_in_another_thread(threading.Thread))  # P-chan

    print("After the bath:", meet())                                     # P-chan

    # A context is also where test doubles live: an override registered inside
    # it disappears together with the context
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.override(Water)
        @Injector.singleton
        class CursedSpring(TapWater):
            def warm_up(self) -> None:
                pass  # Jusenkyo water stays cold

        take_a_bath()
        print("In the cursed spring:", meet())                           # P-chan

    with Injector.context(InjectionSubcontextType.RESET):
        take_a_bath()
        print("Back home, plain tap water:", meet())                     # Ryoga Hibiki


if __name__ == "__main__":
    main()
```

</details>

The example shows, in order:

* **An interface and its implementation.** `Water` is registered with `@Injector.interface`, `TapWater` is its
  implementation, and `Provide[Water]` receives the `TapWater` instance of the current context.
* **`@Injector.inject` on `__init__`.** `Ryoga` gets its `Water` when it is instantiated, that is the first time
  `meet()` runs in a context. Each context that creates a `Ryoga` gives it that context's `Water`.
* **`RESET`.** The first `with` block keeps every registration and binding of the root context but gives every
  singleton a fresh, unfrozen slot without an instance. `take_a_bath()` warms up the block's own `TapWater`, and
  `meet()` builds the block's own `Ryoga`, who sees hot water. After the block the root instances are untouched:
  the root `TapWater` was never warmed, so the root `Ryoga` is still `P-chan`.
* **`ContextAwareThread` versus `threading.Thread`.** Akane runs in a `ContextAwareThread` created inside the block,
  which captures the block's context and enters it for the duration of its `run()`, so she meets `Ryoga Hibiki`.
  Ranma runs in a plain `threading.Thread`, which starts in the root context whatever its creator had open, so he
  meets the root `Ryoga` next to the cold root `TapWater`: `P-chan`.
* **An override as a test double scoped to a context.** `CursedSpring` is registered, and overrides `Water`, inside
  the second `RESET` block. The root `Water` was frozen by the first `meet()`, but the block's copy starts unfrozen,
  so the override is accepted. Both the registration and the override disappear with the block: the third block
  resolves `Water` to plain `TapWater` again, and nobody outside the block ever saw `CursedSpring`.

## Context kinds
`Injector.context(kind)` takes a member of `smalldi.context.InjectionSubcontextType`; `RESET` is the default.

| Kind       | What the new context shares with its parent                                                                                                                                                                                                                                      |
|------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `PRESERVE` | The same `InjectionContext` object as the current one: nothing is copied.                                                                                                                                                                                                        |
| `RESET`    | The same registrations, implementations and overrides; every singleton is a fresh, unfrozen `LazySingleton` without an instance. Classes sharing one singleton through an override keep sharing one, and interfaces are rebound to the new singletons. The default kind.           |
| `EMPTY`    | Nothing: no singleton and no interface is registered.                                                                                                                                                                                                                            |
| `SHALLOW`  | A new registry dict holding the *same* `LazySingleton` objects: instances and frozen state are shared with the parent. Singletons registered inside are invisible to the parent. Overriding an inherited singleton inside the block mutates the shared object and is visible in the parent. |
| `STACK`    | Each singleton's effective class (its override if it has one, else its own class) becomes the base of a fresh singleton with no override; classes that shared one singleton keep sharing one. An interface's override becomes its implementation, so it can be overridden again.      |

Rules:

* Contexts are tracked per *execution slice*: the running `asyncio.Task` if code runs inside a Task, otherwise the
  current `threading.Thread` object. A slice with nothing pushed sees the root context. `Injector.get_context()`
  returns the current slice's context.
* A `threading.Thread` starts in the root context, regardless of the context of the thread that created it.
  `smalldi.thread.ContextAwareThread` captures the creator's current `InjectionContext` in `__init__` (the object
  itself, not a copy) and enters it for the duration of `run()`.
* An `asyncio.Task` starts in the root context. Opening injection contexts inside coroutines is not supported.
  `@Injector.inject` on an `async def` returns a coroutine function and resolves `Provide[T]` when the coroutine starts
  running.
* `Injector.context(kind)` and `Injector.foreign_context(ctx)` return a single-use context manager. Nothing is pushed
  until `__enter__`; the child context is built from the context that is current at `__enter__` time, and `__enter__`
  returns the `InjectionContext`. `__exit__` pops exactly the context this manager pushed: exiting out of order
  raises `RuntimeError` and leaves the stack unchanged, and entering the same manager twice raises `RuntimeError`.
* If a slice ends with contexts still open, they are removed and a `ResourceWarning` is emitted.
* A registration goes into the context that is current when the decorator runs. Python caches modules: a module
  first imported inside `with Injector.context(...)` keeps its registrations in that context only, and importing it
  again at the root does nothing. Import the modules that register singletons at the root.
* A request for an instance freezes what it looks up in the current context. A `RESET` or `STACK` child starts
  with everything unfrozen; a `SHALLOW` child shares the parent's frozen state, and `PRESERVE` is the parent.

## Declared contexts
`smalldi.context.InjectionContextOverride` is a dataclass base whose fields declare a `SHALLOW` child context, a
declared context: every declared class gets a singleton of its own in the block, every interface declared as
`ImplementationOf[I]` a binding of its own, and a default value becomes that singleton's instance or that interface's
implementation.

<details>
<summary>Stormy and Pip come to visit</summary>

```python
import abc
import dataclasses

from smalldi import ImplementationOf, Injector, Provide
from smalldi.context import InjectionContextOverride


@Injector.singleton
class CookieJar:
    def __init__(self):
        self.cookies = 3

    def take(self):
        self.cookies -= 1
        return "cookie"


@Injector.singleton
class NapSpot:
    def __init__(self, name="the sofa"):
        self.name = name


class SnackBowl:
    def __init__(self, snacks=5):
        self.snacks = snacks


@Injector.inject
def snack_time(who, jar: Provide[CookieJar] = None, spot: Provide[NapSpot] = None):
    print(f"{who} takes a {jar.take()} ({jar.cookies} left) and naps on {spot.name}")


snack_time("Pusheen")  # Pusheen takes a cookie (2 left) and naps on the sofa


# Stormy comes to visit. She gets her own cookie jar, a snack bowl nobody else
# has, and a nap spot of her own, while Pusheen's things stay as they are.
@dataclasses.dataclass
class StormyVisits(InjectionContextOverride):
    jar: CookieJar                              # the block's own jar, built on first use: full again
    bowl: SnackBowl                             # not registered outside: injectable in the block only
    spot: NapSpot = dataclasses.field(                  # the block's own NapSpot, with a new instance per visit
        default_factory=lambda: NapSpot("the windowsill"))


with Injector.context(StormyVisits):
    snack_time("Stormy")  # Stormy takes a cookie (2 left) and naps on the windowsill
    print(Injector.get_instance(SnackBowl).snacks)  # 5

# Pip visits with a bowl of his own: an instance gives the values, and None presets nothing.
with Injector.context(StormyVisits(jar=None, bowl=SnackBowl(snacks=2), spot=NapSpot("the cardboard box"))):
    snack_time("Pip")  # Pip takes a cookie (2 left) and naps on the cardboard box
    print(Injector.get_instance(SnackBowl).snacks)  # 2

snack_time("Pusheen")  # Pusheen takes a cookie (1 left) and naps on the sofa
print(Injector.is_singleton(SnackBowl))  # False


@Injector.singleton
class Blanket:
    def __init__(self, colour="grey"):
        self.colour = colour


# Pip's blanket is the block's own Blanket; the one outside stays grey.
@dataclasses.dataclass
class PipBringsABlanket(InjectionContextOverride):
    blanket: Blanket = dataclasses.field(default_factory=lambda: Blanket("pink"))


with Injector.context(PipBringsABlanket):
    print(Injector.get_instance(Blanket).colour)  # pink
print(Injector.get_instance(Blanket).colour)  # grey


@Injector.interface
class Toy(abc.ABC):
    @abc.abstractmethod
    def squeak(self): ...


@Injector.implements(Toy)
@Injector.singleton
class Ball(Toy):
    def squeak(self):
        return "boing"


class Feather(Toy):
    def squeak(self):
        return "swish"


@Injector.inject
def play(who, toy: Provide[Toy] = None):
    print(f"{who} plays with the {type(toy).__name__.lower()}: {toy.squeak()}")


play("Pusheen")  # Pusheen plays with the ball: boing


# Pip brings a feather: in the block, Toy is the feather; Pusheen's ball stays bound outside.
@dataclasses.dataclass
class PipBringsAToy(InjectionContextOverride):
    toy: ImplementationOf[Toy] = dataclasses.field(default_factory=Feather)


with Injector.context(PipBringsAToy):
    play("Pip")  # Pip plays with the feather: swish
    print(Injector.is_singleton(Feather))  # False: the feather is held by the block's binding of Toy alone
play("Pusheen")  # Pusheen plays with the ball: boing


# Stormy picks a toy inside the block: without a value, the block's binding of Toy starts unbound.
@dataclasses.dataclass
class StormyPicksAToy(InjectionContextOverride):
    toy: ImplementationOf[Toy]


with Injector.context(StormyPicksAToy):
    # implement before playing: a request freezes the block's binding
    @Injector.implements(Toy)
    @Injector.singleton
    class Mouse(Toy):
        def squeak(self):
            return "squeak"

    play("Stormy")  # Stormy plays with the mouse: squeak
play("Pusheen")  # Pusheen plays with the ball: boing
print(Injector.is_singleton(Mouse))  # False


# A plain field can't declare an abstract class: the toy is declared as ImplementationOf[Toy].
@dataclasses.dataclass
class PipDeclaresTheToy(InjectionContextOverride):
    toy: Toy = Ball()


try:
    with Injector.context(PipDeclaresTheToy):
        pass
except TypeError as e:
    print(type(e).__name__)  # TypeError
```

</details>

Rules:

* Subclass `InjectionContextOverride`, decorate the subclass with `@dataclasses.dataclass` and pass it to
  `Injector.context`, which returns its usual single-use context manager. The class form, `Injector.context(Fixture)`,
  takes the fields' defaults as the values; the instance form, `Injector.context(Fixture(...))`, takes the instance's
  attributes, and a value of None presets nothing. `Fixture.apply(context)`, on the class or an instance, derives the
  same child from a given `InjectionContext` and returns it without pushing it. Fields without a default go first, as
  in every dataclass. A subclass with no dataclass among its bases works in the class form, through its annotations
  and class attributes; a subclass of a decorated subclass must be decorated itself, else `TypeError`.
* The child is the `SHALLOW` kind: every singleton not declared is the parent's own `LazySingleton` object.
* `name: T` gives the child a `LazySingleton` of its own for `T`. For a registered `T` it is a clone of `T`'s
  singleton, made as `RESET` makes it: same class and override class, no instance, not frozen. Instances created and
  overrides declared for `T` in the block stay in the block, and classes sharing one singleton with `T` share the
  clone. An unregistered `T` is registered in the child only and constructed on first use. `T` is a concrete class.
* `name: ImplementationOf[I]`, `I` an abstract class, gives the child a binding of its own for the interface `I`.
  Without a value the binding has neither implementation nor override, whatever the parent's binding has, so the
  block binds it with `@Injector.implements(I)` or `@Injector.override(I)` on a singleton registered in the block or
  declared as a field. A request for `I` before it is bound raises `RuntimeError` and freezes the block's binding. An
  `I` the parent doesn't know is registered in the child only. `ImplementationOf[I] | None`,
  `Optional[ImplementationOf[I]]` and `ImplementationOf[I | None]` declare `I` as well.
* `name: ImplementationOf[I] = instance`, or `dataclasses.field(default_factory=...)`, binds `instance` as the
  implementation of `I` and freezes the binding: `Provide[I]` is `instance` in the block, and the binding accepts no
  override. The instance is held by a singleton of the binding alone: `type(instance)` is not registered by the
  preset, so `Provide[type(instance)]` resolves as in the parent, and several interface fields may hold instances of
  one class, or one object, as may a concrete field and an interface field. `instance` must be an instance of `I`,
  else `TypeError` from `Injector.context()` or `apply()`; a mock built with `spec=I` passes, a class object or a
  bare mock doesn't. A context opened inside the block shares the preset if it is `SHALLOW`, `PRESERVE` or
  declared, and has an unbound binding for `I` if it is `RESET` or `STACK`: nothing is constructed there, and the
  nested block binds `I` itself or gets `RuntimeError` on request. The block's binding is unchanged afterwards.
* The parent's binding for `I` is never changed, and the parent's other interfaces stay bound in the child, to the
  clones where their singletons are declared. The child is `SHALLOW`, so overriding the block's `I` with an inherited,
  undeclared singleton marks that shared object, and a request through the binding freezes it, as in any `SHALLOW`
  child; declare that singleton as a field, or register the implementation in the block.
* A plain field of an abstract class, registered with `@Injector.interface` or not, raises `TypeError` when the
  context manager is created, on every call; the message names `ImplementationOf[I]` as the spelling. So does
  `ImplementationOf[C]` with a concrete `C`; the message names `name: C`.
* `name: T = instance`, or `dataclasses.field(default_factory=...)`, makes `instance` the instance of the child's
  singleton for `T` and freezes it. The parent never sees it. `instance` is not checked against `T`.
* A plain default value is one object, preset in every context derived from the class: the class form uses it, and
  so does every instance built without that argument. `Injector.context()` and `apply()` warn about it with
  `UserWarning` once per class, on first use, and use it as it is. A `default_factory` makes a new object per
  context and doesn't warn; neither does a default of None.
* A default factory runs once per `Injector.context()` or `apply()` call in the class form, and never in the
  instance form, where the dataclass constructor ran it already. Two fields of one class or interface, a
  `Provide[T]` field or an annotation that is not a class raise `TypeError` from `Injector.context()` or `apply()`.
  The child is built at `__enter__` from the context current then; two concrete fields resolving to one singleton
  raise `TypeError` there, and nothing is pushed. The parent's objects are never changed.
* `smalldi.context.InjectionContextSingletonOverride` and `smalldi.InjectionContextSingletonOverride` are deprecated
  aliases of `InjectionContextOverride`: importing or accessing either warns with `DeprecationWarning`, and they are
  removed no earlier than 1.0.0.

The [docs](https://github.com/0xf104a/smalldi/blob/master/docs/index.md) have diagrams of what each kind shares with
its parent and of the per-slice context stacks ([contexts](https://github.com/0xf104a/smalldi/blob/master/docs/contexts.md)),
the objects behind the registry ([architecture](https://github.com/0xf104a/smalldi/blob/master/docs/architecture.md))
and the locking model ([concurrency](https://github.com/0xf104a/smalldi/blob/master/docs/concurrency.md)).

# Utilities
## Concurrency
`smalldi.concurrency` provides two decorators for serializing calls between threads:

* `@synchronized` guards a function with its own reentrant lock, shared by every caller.
* `@threadsafe` picks the lock from where the method is defined:
  * instance methods lock per instance,
  * `@classmethod`s lock per class (subclasses get their own lock),
  * `@staticmethod`s lock per function, like `@synchronized`.

  Applied outside a class body, it warns and falls back to `@synchronized`.

### Limitations
* Async functions (`async def` and async generators) aren't supported yet: decorating one raises `NotImplementedError`.
* Plain generator functions are accepted, but the lock is held only while the generator object is created,
  not while it is iterated. Don't rely on either decorator to protect a generator's body.
* `@threadsafe` stores the instance lock as `__instance_mutex__` in the object's `__dict__` the first time
  a guarded method runs. Classes using `__slots__` must list `__instance_mutex__` in their slots.
* Once that lock exists, the object can't be pickled or deep-copied (`TypeError: cannot pickle '_thread.RLock' object`),
  and `copy.copy` makes the copy share the original's lock. If you need copying, drop the lock from the state,
  and a fresh one is created on the next call:
```python
  def __getstate__(self):
      state = self.__dict__.copy()
      state.pop("__instance_mutex__", None)
      return state
```

### Oneshot
`smalldi.decorator.oneshot` makes a function run once per level and return the first result on every later call.

<details>
<summary>Pusheen's snack cupboard</summary>

```python
import dataclasses

from smalldi.decorator import oneshot, OneshotLevel


@oneshot
def open_cupboard():
    print("creak")
    return ["cookie", "tuna", "cookie"]


print(open_cupboard() is open_cupboard())  # creak, then True: opened once, same list


@dataclasses.dataclass
class Cat:
    name: str

    @oneshot(OneshotLevel.PER_INSTANCE)
    def favourite_snack(self):
        print(f"{self.name} picks")
        return open_cupboard()[0]


pusheen, stormy = Cat("Pusheen"), Cat("Stormy")
print(pusheen.favourite_snack())  # Pusheen picks, then cookie
print(pusheen.favourite_snack())  # cookie: Pusheen picked already
print(stormy.favourite_snack())   # Stormy picks, then cookie: Stormy picks for herself
```

</details>

Rules:

* `@oneshot` and `@oneshot()` are the `GLOBAL` level: the function runs once everywhere. `@oneshot(OneshotLevel.PER_CLASS)`
  runs it once per class, the `cls` of a classmethod or `type(self)` of an instance method;
  `@oneshot(OneshotLevel.PER_INSTANCE)` runs it once per instance, on instance methods only.
* On a classmethod or a staticmethod, `@oneshot` goes above `@classmethod` / `@staticmethod`.
* A call that raises stores nothing, so the next call runs the function again. A re-entrant call for the same key
  raises `RuntimeError`. Concurrent first calls run the function once; the other callers wait for its result.

## Collector
`Collector` is a class which imports all modules in order execute decorators.

> [!WARNING]
> Collector should be used in top-level modules of the project as calling it from a submodule which is imported by 
> other submodules may lead to circular imports.

### `Collector.collect_from_package`
This method imports all modules in a given package.
