# Small DI
The smallest dependency injection mechanism possible in python.
SmallDI provides you with an intuitive and simple interface for doing dependency
injections in your project.

SmallDI is built around three features: [singletons](#singletons), [containers](#containers) and
[interfaces](#interfaces).

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

## How singletons work
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes, and interfaces they implement, may be injected at the current state of library development.
Abstract classes can't be singletons.

Singletons are lazy: registering a class doesn't instantiate it. The instance is created, exactly once and in a
thread-safe way, the first time it is needed, that is when an `@Injector.inject`-decorated function is called.
Once an instance was requested, a singleton is *frozen* and can no longer be [overridden](#overrides), even if
creating the instance failed.

A singleton whose constructor requires itself, directly or through its dependencies, raises `RuntimeError`
(circular dependency). Cycles that span several threads, or a constructor waiting for a thread that needs the
singleton being constructed, deadlock instead and aren't detected.

> [!WARNING]
> Every class is registered once: registering the same class twice raises `TypeError`. A reloaded module
> (`importlib.reload`) defines new class objects, which are registered as additional singletons next to the old
> ones without an error. DI is set up once per process; module reloading isn't supported.

## Provide
`Provide[T]` is an annotation for injector telling it that instead of this argument
instance of `T` should be passed. Caller of function with `Provide[T]` may explicitly
override argument annotated with `Provide[T]` by directly passing `annotated_di_arg=my_value`.
Only keyword arguments are recognized: passing the dependency positionally makes the call raise `TypeError`
for a duplicate argument.

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
            bean = coffee_dealer.buy(1)
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
    sys.exit(main())
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
apply it above `@Injector.singleton`.

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

  So declare overrides before anything injects their targets. Frozen means frozen: nothing rebinds a frozen
  target, the only binding still accepted is the first `@Injector.implements` of an interface that already has an
  override, since the override keeps winning.

`SingletonFrozenError` can be imported from `smalldi`.

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

## Collector
`Collector` is a class which imports all modules in order execute decorators.

> [!WARNING]
> Collector should be used in top-level modules of the project as calling it from a submodule which is imported by 
> other submodules may lead to circular imports.

### `Collector.collect_from_package`
This method imports all modules in a given package.