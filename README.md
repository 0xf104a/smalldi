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

# Ask for the interface, get the implementation
@Injector.inject
def feed(bowl: Provide[Bowl]):
    print(bowl.fill())

if __name__ == '__main__':
    feed()
```
    
# Library structure
## Injector
Injector is a static class(i.e., one that should never be instantiated) which is the main (and currently the only)
DI container inside the library. Injector provides three decorators:
* `@Injector.singleton` creates an instance of a class which may further be injected in functions
* `@Injector.inject` replaces parameters annotated with type `Provide[Singleton]` with actual instances of Singleton
* `@Injector.implements(Interface)` binds a singleton to an interface, so `Provide[Interface]` injects it

Dependencies are resolved when `@Injector.inject` is applied, not when the function is called, so every
injected singleton must be declared before the function which uses it.

### Singletons
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes (or interfaces bound to them) may be injected at the current state of library development.

### Interfaces
`@Injector.implements(Interface)` binds a singleton class to an interface (usually an abstract class), so
parameters annotated with `Provide[Interface]` receive the instance of that singleton. The decorated class must
be a concrete subclass of the interface and must already be a singleton, i.e. `@Injector.implements` goes above
`@Injector.singleton`. The class is still injectable directly as `Provide[Implementation]`.

An interface may be rebound to another implementation (e.g. in tests or plugins) until it is injected for the first
time. After that the binding is frozen and rebinding to a different implementation raises `InterfaceFrozenError`,
because functions which were already decorated hold the old implementation.

> [!NOTE]
> `Injector.singletons_available` is deprecated since 0.3.0 and emits `DeprecationWarning`.
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

## `Container._get_components`
The container exposes protected method `_get_components` which returns an iterable of all components
registered in the container (the decorated classes or functions themselves). Full
[registrations](#componentregistration) are stored in the `components` attribute.

## `Container._on_component_register`
The container has protected method `_on_component_register(registration)` which is called with the
[registration](#componentregistration) every time a new component is registered in the container.

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