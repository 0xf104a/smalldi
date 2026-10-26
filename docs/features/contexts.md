# Contexts

A context is a registry of singletons and interfaces. `with Injector.context(kind):` makes a child context current
for the block, so registrations, overrides and instances made inside stay inside; `RESET`, the default kind, keeps
every registration and override of the parent but starts with fresh, unfrozen singletons without instances.

## Example

```python
import dataclasses

from smalldi import Injector, Provide
from smalldi.context import InjectionContextOverride


@Injector.singleton
class CookieJar:
    def __init__(self):
        self.cookies = 3

    def take(self):
        self.cookies -= 1
        return f"a cookie, {self.cookies} left"


@Injector.inject
def snack_time(jar: Provide[CookieJar]):
    return jar.take()


print(snack_time())  # a cookie, 2 left

with Injector.context():  # RESET: same registrations, a fresh jar for the block
    @Injector.override(CookieJar)  # declared before the block asks for a jar
    @Injector.singleton
    class BottomlessJar(CookieJar):
        def take(self):
            return "a cookie, plenty left"

    print(snack_time())  # a cookie, plenty left

print(snack_time())  # a cookie, 1 left: the jar outside is untouched and the override is gone
print(Injector.is_singleton(BottomlessJar))  # False


# A declared context presets instances for the block, field by field.
@dataclasses.dataclass
class StormyVisits(InjectionContextOverride):
    jar: CookieJar = dataclasses.field(default_factory=CookieJar)


with Injector.context(StormyVisits):
    print(snack_time())  # a cookie, 2 left: Stormy's own full jar

print(snack_time())  # a cookie, 0 left: Pusheen's jar again
```

## Context kinds

`Injector.context(kind)` takes a member of `smalldi.context.InjectionSubcontextType`:

| Kind       | The block gets                                                                                                         | Use it for                                                       |
|------------|------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| `RESET`    | The same registrations, implementations and overrides, every singleton fresh and unfrozen. The default.                | One test, one request, one job that wants its own instances      |
| `STACK`    | Like `RESET`, but each override becomes the base class of its singleton, so everything can be overridden again        | Stacking a fake on top of an override already in place           |
| `SHALLOW`  | A new registry sharing the parent's singleton objects: instances and frozen state are shared, new registrations aren't | Registering extra singletons that the parent shouldn't see       |
| `EMPTY`    | Nothing registered                                                                                                     | Code that registers everything it needs itself                   |
| `PRESERVE` | The parent context itself                                                                                              | A `with` block that must not change the context                  |

A declared context, an `InjectionContextOverride` subclass passed as the kind, is a `SHALLOW` child where every field
names a singleton of the block's own, optionally with a preset instance, and `ImplementationOf[I]` fields give the
block its own binding of the interface `I`, bound to a preset instance of `I` if the field has one; the preset's class
is not registered by it. A `SHALLOW`, `PRESERVE` or declared context opened inside the block shares the preset; a
`RESET` or `STACK` one starts with `I` unbound, since a preset is a value and not a registration to rebuild.

## What to know

* The child is built from the context current when the block is entered, and the block's registrations go into it.
  Python caches modules, so a module first imported inside a context keeps its registrations in that context: import
  the modules that register singletons at the root of the program.
* Contexts are tracked per execution slice, the running `asyncio.Task` or else the current thread. A new thread or
  task starts in the root context; `smalldi.thread.ContextAwareThread` runs in the context of the code that created
  it. Opening contexts inside coroutines isn't supported.
* A frozen singleton is frozen in its context only: a `RESET` or `STACK` child starts unfrozen, which is where an
  override of something already injected at the root goes.
* The context manager is single-use, nothing is pushed before `__enter__`, and exiting out of order raises
  `RuntimeError`. A thread or task ending with contexts still open gets them removed with a `ResourceWarning`.

## Read on

* [README: Contexts](../../README.md#contexts), the example, the kinds and the declared-context rules in full
* [Contexts in depth](../contexts.md), before/after diagrams of every kind and of the per-thread context stacks
* [Use case: testing](../use-cases/testing.md)
* [Use case: threads and asyncio](../use-cases/threads-and-async.md)
