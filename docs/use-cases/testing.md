# Testing

Three tools cover most tests: a `RESET` context per test gives every test fresh instances and forgets its overrides;
an override declared inside the context swaps in a fake; a declared context presets an instance, such as a
`unittest.mock.Mock`, for the block. The code under test keeps asking for `Provide[T]` and never knows it is being
tested.

## Example

The tests below are plain functions, called at the end, so the file runs as-is; the next section shows the same
thing as a pytest fixture.

```python
import dataclasses
from unittest import mock

from smalldi import Injector, Provide
from smalldi.context import InjectionContextOverride


# The code under test
@Injector.singleton
class Pantry:
    def __init__(self):
        self.cookies = 3

    def take(self):
        if not self.cookies:
            raise LookupError("no cookies left")
        self.cookies -= 1
        return "cookie"


@Injector.singleton
class Pusheen:
    @Injector.inject
    def __init__(self, pantry: Provide[Pantry]):
        self.pantry = pantry

    def snack(self):
        return self.pantry.take()


@Injector.inject
def snack_time(cat: Provide[Pusheen]):
    return cat.snack()


# 1. A fresh context per test: instances made in one test are gone in the next.
def test_snack_time_takes_a_cookie():
    with Injector.context():
        assert snack_time() == "cookie"
        assert Injector.get_instance(Pantry).cookies == 2


def test_the_pantry_is_full_again():
    with Injector.context():
        assert Injector.get_instance(Pantry).cookies == 3


# 2. A fake declared inside the context, before the test asks for the pantry.
def test_an_empty_pantry():
    with Injector.context():
        @Injector.override(Pantry)
        @Injector.singleton
        class EmptyPantry(Pantry):
            def take(self):
                raise LookupError("no cookies left")

        try:
            snack_time()
        except LookupError as e:
            assert str(e) == "no cookies left"
        else:
            raise AssertionError("snack_time should have failed")


# 3. A mock preset through a declared context. Pusheen is declared too, so the cat built with the
#    mock stays in the block instead of becoming the shared instance.
@dataclasses.dataclass
class PantryFixture(InjectionContextOverride):
    pantry: Pantry = None  # None presets nothing: the block gets a pantry of its own
    cat: Pusheen = None


def test_with_a_mock():
    pantry = mock.Mock(spec=Pantry)
    pantry.take.return_value = "tuna"
    with Injector.context(PantryFixture(pantry=pantry)):
        assert snack_time() == "tuna"
    pantry.take.assert_called_once_with()


for test in (test_snack_time_takes_a_cookie, test_the_pantry_is_full_again, test_an_empty_pantry, test_with_a_mock):
    test()
    print(f"{test.__name__} passed")
```

## With pytest

An autouse fixture opens a `RESET` context around every test. Tests then declare overrides or open declared contexts
inside it as above. The fixture yields the `InjectionContext` in case a test wants to look at it.

```python title="conftest.py"
import pytest

from smalldi import Injector


@pytest.fixture(autouse=True)
def injection_context():
    with Injector.context() as context:
        yield context
```

Import the modules under test at the top of the test modules, not inside a test or a fixture: a module first imported
inside a context keeps its registrations in that context and is never imported again.

## Which tool when

* **Fresh instances only:** `with Injector.context():`. The block keeps every registration, implementation and
  override of the root and builds its own instances on demand.
* **A fake with behaviour:** subclass the real class, decorate it with `@Injector.override(Real)` above
  `@Injector.singleton` inside the block, before anything in the block requests `Real`. An interface is faked the same
  way, with the interface as the target.
* **A ready-made object, such as a mock:** a declared context. A field `name: T = None` gives the block a singleton
  of its own for `T`, and passing an instance, `Fixture(name=obj)`, presets it. `name: ImplementationOf[I] = obj`
  binds the interface `I` to `obj`, which must be an instance of `I`: a mock built with `spec=I` is one. The class of
  `obj` is not registered, so one fake class, or one object, may serve several interface fields. Declare every
  singleton that depends on the preset as a field too, so the instances built with it stay in the block: a declared
  context is `SHALLOW`, and an undeclared singleton is the one the parent sees. A `RESET` or `STACK` context opened
  inside the block doesn't keep the preset: `I` is unbound there until the nested block binds it, and nothing is
  constructed from the preset's class.
* **One function, one call:** pass the dependency as a keyword argument, `snack_time(cat=fake_cat)`. No context
  needed.
* **The root already overrides what the test wants to fake:** open `Injector.context(InjectionSubcontextType.STACK)`
  instead of `RESET`; each override becomes the base of its singleton and can be overridden again.

## Read on

* [Contexts](../features/contexts.md), the kinds in short, and [Contexts in depth](../contexts.md), with diagrams
* [README: Declared contexts](../../README.md#declared-contexts), every rule of `InjectionContextOverride` and
  `ImplementationOf`
* [Swapping implementations](swapping-implementations.md), the same overrides outside tests
