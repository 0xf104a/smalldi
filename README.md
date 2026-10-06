# Small DI
The smallest dependency injection mechanism possible in python.
SmallDI provides you with an intuitive and simple interface for doing dependency
injections in your project.

# Example usage
## Injection
```python
import random

from smalldi import Injector
from smalldi.annotation import Provide

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

## Container
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

## Interfaces
```python
from abc import ABC, abstractmethod

from smalldi import Injector, Provide

# Define interface for a cat bowl
class Bowl(ABC):
    @abstractmethod
    def fill(self) -> str:
        pass

# Bind an implementation to the interface.
# Note that @Injector.implements must be placed above @Injector.singleton
@Injector.implements(Bowl)
@Injector.singleton
class FishBowl(Bowl):
    def fill(self) -> str:
        return "Fish!"

# Replace the baseline implementation, e.g. in a plugin or in tests.
# An interface may be overridden only once
@Injector.override(Bowl)
@Injector.singleton
class MilkBowl(Bowl):
    def fill(self) -> str:
        return "Milk!"

# Ask for the interface, get the implementation (MilkBowl here)
@Injector.inject
def feed(bowl: Provide[Bowl]):
    print(bowl.fill())

if __name__ == '__main__':
    feed()
```
    
# Library structure
## Injector
Injector is a static class(i.e., one that should never be instantiated) which is the main (and currently the only)
DI container inside the library. Injector provides four decorators:
* `@Injector.singleton` registers a class whose single instance may further be injected in functions
* `@Injector.inject` replaces parameters annotated with type `Provide[Singleton]` with actual instances of Singleton
* `@Injector.implements(Interface)` binds a singleton to an interface, so `Provide[Interface]` injects it
* `@Injector.override(Interface)` replaces the implementation bound with `@Injector.implements`

Dependencies are resolved when the decorated function is first called, not when `@Injector.inject` is applied,
so singletons, interfaces and overrides may be declared in any order, as long as they are declared before the
first call. A missing dependency raises `TypeError` on call. Dependencies passed explicitly by the caller
are not resolved. Note that this also means that whether a late binding fails with `InterfaceFrozenError` depends
on whether a function injecting the interface was already called.

### Singletons
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes (or interfaces bound to them) may be injected at the current state of library development.
Singletons are lazy: the instance is created when the singleton is first injected, so `__init__` side effects
happen then, not when the class is declared, and errors raised by `__init__` surface on first use.
A singleton is never created if it is never injected. Creation is thread-safe (singletons are created under a
single lock), and a circular dependency between singletons raises `TypeError`, also when threads race on it.
Decorating a class with `@Injector.singleton` twice raises `ValueError`. A class used as an interface can't be a
singleton and vice versa: either order raises `TypeError`.

### Interfaces
`@Injector.implements(Interface)` binds a singleton class to an interface (usually an abstract class), so
parameters annotated with `Provide[Interface]` receive the instance of that singleton. The decorated class must
be a concrete subclass of the interface and must already be a singleton, i.e. `@Injector.implements` goes above
`@Injector.singleton`. The interface itself must not be a singleton. The class is still injectable directly as `Provide[Implementation]`.

Each interface has exactly one baseline implementation; binding a second one with `@Injector.implements` raises
`InterfaceAlreadyBoundError`. To replace the baseline (e.g. in tests or plugins) use
`@Injector.override(Interface)`, which has the same requirements as `@Injector.implements`. The override takes
precedence over the baseline and may be declared before or after it, so module import order doesn't matter.
An interface may be overridden only once: a second, different override raises `InterfaceAlreadyBoundError`.
The baseline remains injectable directly as `Provide[Baseline]`.

`@Injector.override` accepts an optional predicate `on`, which makes the override conditional:
```python
import os

@Injector.override(Bowl, on=lambda: os.environ.get("CAT_DIET") == "milk")
@Injector.singleton
class MilkBowl(Bowl):
    def fill(self) -> str:
        return "Milk!"
```
`on` is called once, when the decorator is applied, not when the interface is injected. If it returns false the
override is skipped: the class stays a regular singleton, the interface keeps its baseline and the override slot
remains free for another `@Injector.override`. The override is validated regardless of `on`, so an invalid
override fails in every environment. `on` must be callable, so `on=False` raises `TypeError`.

Once an interface is injected for the first time its implementation is frozen, because functions which were
already called hold it. After that, any binding that would change which implementation the interface
resolves to (e.g. an override of an already injected baseline) raises `InterfaceFrozenError`.

> [!NOTE]
> `Injector.singletons_available` is deprecated since 0.3.0 and emits `DeprecationWarning`.
> It returns a read-only snapshot containing only singletons which were already created; it never creates any.
> Use `@Injector.inject` to obtain singletons instead.

## Provide
`Provide[T]` is an annotation for injector telling it that instead of this argument
instance of `T` should be passed. Caller of function with `Provide[T]` may explicitly
override argument annotated with `Provide[T]` by directly passing `annotated_di_arg=my_value`.

## Container
Container helps to collect classes and potential functions into a single unit.
All containers must be singletons inherited from `Container` class.
To create a container, write and inheritor of `Container` class and annotate it with `@Injector.singleton`.
Then you may register components in the container by annotating them with `@MyContainer.component`.
Additionally, `@MyContainer.component` may be called with `()` in order to provide metadata about the component.
Registering a component doesn't create the container. Components belong to the container class, so a container
also has components registered in the container classes it inherits from.

## `Container._get_components`
The container exposes protected method `_get_components` which returns an iterable of all components
registered in the container (the decorated classes or functions themselves). Full
[registrations](#componentregistration) are stored in the `components` attribute.

## `Container._on_component_register`
The container has protected method `_on_component_register(registration)` which is called with the
[registration](#componentregistration) every time a new component is registered in the container.
Components registered before the container is created are passed to it right after creation. The hook is
called without holding the container's lock, so it may register components and inject singletons.

## ComponentRegistration
`ComponentRegistration` is a dataclass which holds information about registered component which
consists of:
* `component`: an actual component type
* `args`: arguments passed to `@MyContainer.component` during registration
* `kwargs`: keyword arguments passed to `@MyContainer.component` during registration

## Collector
`Collector` is a class which imports all modules in order execute decorators.

> [!WARNING]
> Collector should be used in top-level modules of the project as calling it from a submodule which is imported by 
> other submodules may lead to circular imports.

### `Collector.collect_from_package`
This method imports all modules in a given package. 