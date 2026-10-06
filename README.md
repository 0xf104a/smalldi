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
DI container inside the library. Injector provides these decorators:
* `@Injector.singleton` registers a class whose instance may further be injected in functions
* `@Injector.interface` marks an abstract class as an [interface](#interfaces) singletons may implement
* `@Injector.implements(...)` declares which interfaces a singleton implements
* `@Injector.override(...)` makes a singleton injected instead of interfaces' implementations or other singletons
* `@Injector.inject` replaces parameters annotated with type `Provide[Singleton]` (or `Provide[Interface]`) with actual
  instances of Singleton. Every `Provide[]` dependency must already be registered when the function is decorated,
  otherwise `TypeError` is raised.

### Singletons
Singletons are classes having a single instance. In `smalldi` singletons may not take constructor(`__init__`) other
than annotated with `Provide[]` type. Only singletons may be decorated with `@Injector.singleton`. As a consequence, 
only singleton classes, and interfaces they implement, may be injected at the current state of library development.
Abstract classes can't be singletons.

Singletons are lazy: registering a class doesn't instantiate it. The instance is created, exactly once and in a
thread-safe way, the first time it is needed, that is when an `@Injector.inject`-decorated function is called.
Once created, a singleton is *frozen* and can no longer be overridden.

### `Injector.singletons`
`Injector.singletons` is a read-only mapping of every registered singleton class to its instance.
Reading it creates every singleton that doesn't exist yet, so it freezes the whole registry.
`Injector.singletons_available` is a deprecated alias for it.

> [!WARNING]
> Registering the same class (or a class with the same module and qualified name, as happens after
> `importlib.reload`) twice emits a `RuntimeWarning` and replaces the registration. Instances which were
> already injected aren't replaced, so several instances of a "singleton" may coexist. DI is normally
> set up once per process; reload modules at your own risk.

### Interfaces
An interface lets code depend on an abstraction instead of a concrete singleton. Mark the abstraction with
`@Injector.interface`, then declare the implementing singleton with `@Injector.implements`, applied *above*
`@Injector.singleton`:
```python
from abc import ABC, abstractmethod

from smalldi import Injector, Provide

@Injector.interface
class Storage(ABC):
    @abstractmethod
    def save(self, data: str): ...

@Injector.implements(Storage)
@Injector.singleton
class FileStorage(Storage):
    def save(self, data: str):
        print(f"Saving {data}")

@Injector.inject
def main(storage: Provide[Storage]):
    storage.save("meow")  # FileStorage instance
```
Rules:
* Each interface has at most one implementation; declaring a second one raises `TypeError`. A singleton may implement
  several interfaces at once: `@Injector.implements(Storage, Cache)`. If any of them can't be bound, none is.
* The singleton must be a subclass of every interface it implements (virtual subclasses registered with
  `ABC.register` count).
* `Provide[Interface]` receives the same instance as `Provide[Implementation]`.
* A function may be decorated with `@Injector.inject` before the interface is implemented, as long as the interface
  itself is registered. Calling it while the interface has neither an implementation nor an override raises
  `NotImplementedError`.
* Interfaces must be abstract classes (with at least one abstract method), so a class can't be both an interface and
  a singleton.
* Interfaces aren't listed in `Injector.singletons`, only their implementations are.
* Registering an interface twice emits a `RuntimeWarning`, like singletons do. Registering the same class again drops
  its implementation and override, which must then be declared again.

### Overrides
`@Injector.override` makes another singleton injected instead of an interface's implementation or instead of another
singleton, for example to swap in a fake in tests or a platform-specific implementation. Like `@Injector.implements`,
apply it above `@Injector.singleton`:
```python
@Injector.override(Storage)       # an interface
@Injector.singleton
class MemoryStorage(Storage):
    def save(self, data: str):
        self.saved = data

@Injector.override(MeowService)   # a singleton
@Injector.singleton
class QuietMeowService(MeowService):
    def meow(self):
        pass
```
`Provide[Storage]` then receives the `MemoryStorage` instance and `Provide[MeowService]` the `QuietMeowService`
instance: the same objects `Provide[MemoryStorage]` and `Provide[QuietMeowService]` receive. Rules:
* The overriding class must be a singleton and a subclass of every target; a class can't override itself.
  Several targets may be overridden at once: `@Injector.override(Storage, FileStorage)`. If any of them can't be
  overridden, none is.
* An overridden singleton is never instantiated through the injector, and `Injector.singletons` maps it to its
  override's instance.
* An interface override wins whatever the import order: it may be declared before or after `@Injector.implements`, and
  an implementation declared later doesn't replace it. An interface with only an override is injectable too. The
  implementation stays registered, so `Provide[FileStorage]` still receives a `FileStorage`, unless `FileStorage` is
  overridden as well.
* Overrides are followed transitively: if `QuietMeowService` is overridden too, `Provide[MeowService]` receives the
  last override's instance. An interface whose implementation is overridden resolves to that override as well.
* Each interface or singleton may have only one override, so it is unambiguous what gets injected: a second override
  with another class raises `TypeError`. Declaring the same class again (e.g. after a reload) is allowed.
* Targets are *frozen* once injected, and overriding a frozen target raises `SingletonFrozenError`:
  * an interface the first time `Provide[Interface]` is resolved, or when `Injector.singletons` is read. Injecting
    the implementation class directly (`Provide[FileStorage]`) doesn't freeze its interfaces;
  * a singleton once its instance is created: by injecting it (directly or through an interface it implements), by
    reading `Injector.singletons`, or, for containers, by registering the first component.

  So declare overrides before anything injects their targets.

`SingletonFrozenError` can be imported from `smalldi`.

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

Registering the first component creates the container instance, so a container can only be
[overridden](#overrides) before any component is registered in it. Components registered afterwards through
`@MyContainer.component` go to the overriding container's instance.

### `Container._get_components`
The container expose protected method `_get_components` which returns all components registered in the container 
in form of iterable of [registrations](#ComponentRegistration).

### `Container._on_component_registered`
The container have protected method `_on_component_registered` which is called every time a new component is registered
in the container.

## ComponentRegistration
`ComponentRegistration` is a dataclass which holds information about registered component which
consists of:
* `component`: an actual component type
* `args`: arguments passed to `@MyContainer.component` during registration
* `kwargs`: keyword arguments passed to `@MyContainer.component` during registration

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