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
    
# Library structure
## Injector
Injector is a static class(i.e., one that should never be instantiated) which is the main (and currently the only)
DI container inside the library. Injector provides two decorators:
* `@Injector.singleton` creates an instance of a class which may further be injected in functions
* `@Injector.inject` replaces parameters annotated with type `Provide[Singleton]` with actual instances of Singleton

### Singletons
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes may be injected at the current state of library development.

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
The container expose protected method `_get_components` which returns all components registered in the container 
in form of iterable of [registrations](#ComponentRegistration).

## `Container._on_component_registered`
The container have protected method `_on_component_registered` which is called every time a new component is registered
in the container.

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