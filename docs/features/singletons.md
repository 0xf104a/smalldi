# Singletons

A singleton is a class registered with `@Injector.singleton`. It has one instance per [context](contexts.md), built
the first time something asks for it, and `@Injector.inject` passes that instance to every parameter annotated
`Provide[T]`.

## Example

```python
from smalldi import Injector, Provide


@Injector.singleton
class SnackCupboard:
    def __init__(self):
        print("the cupboard creaks open")
        self.snacks = ["cookie", "tuna", "cookie"]

    def take(self):
        return self.snacks.pop(0)


@Injector.singleton
class Pusheen:
    @Injector.inject
    def __init__(self, cupboard: Provide[SnackCupboard]):
        self.cupboard = cupboard

    def snack(self):
        return self.cupboard.take()


@Injector.inject
def snack_time(cat: Provide[Pusheen]):
    print(f"Pusheen eats a {cat.snack()}")


print("nothing is built yet")
snack_time()  # the cupboard creaks open, then: Pusheen eats a cookie
snack_time()  # Pusheen eats a tuna: the same cat, the same cupboard
print(Injector.get_instance(Pusheen).cupboard is Injector.get_instance(SnackCupboard))  # True
```

## What to know

* Registration is lazy. The constructor runs on the first request, at most once per context, and dependencies are
  built on demand in dependency order. A class that needs itself, directly or through its dependencies, raises
  `RuntimeError`.
* A singleton's `__init__` takes no arguments, or is decorated with `@Injector.inject` and takes `Provide[T]`
  parameters only. Abstract classes can't be singletons; they are [interfaces](interfaces.md).
* `@Injector.inject` checks when the function is decorated that every `Provide[T]` names a registered singleton or
  interface, and resolves the instances at every call, in the context current at that call. A keyword argument passed
  by the caller replaces the injected value.
* `Injector.get_instance(T)` returns the instance from code that isn't injected itself, such as the entry point of a
  program or a framework callback.
* The first request freezes the singleton: from then on it accepts no [override](interfaces.md#what-to-know).
* The same instance is returned to every thread. Threads asking for a singleton whose constructor is running wait
  for it instead of building a second one.
* `from smalldi import singleton, inject` are shorthands for `Injector.singleton` and `Injector.inject`.

## Read on

* [README: Singletons](../../README.md#singletons), the full rules, `Provide` and the deprecated
  `Injector.singletons_available`
* [Use case: wiring an application](../use-cases/wiring-an-application.md)
* [Architecture](../architecture.md), the objects behind the registry
