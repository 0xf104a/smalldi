"""
Specification of `InjectionContextSingletonOverride`.

A dataclass subclass declares a `SHALLOW` child context field by field: every
declared class gets a singleton of its own in the child, a clone of the parent's
singleton for a registered class and a registration in the child only for an
unregistered one, and a default value becomes the instance of that singleton.
`Injector.context` takes the subclass, with its defaults, or an instance of it,
with its attributes; `apply(context)` derives the child of a given context
without pushing it. Abstract classes, registered interfaces or not, are refused
as fields. Every test opens its own outer RESET context and registers all of its
classes inside it, so the root context is never touched.
"""
import abc
import dataclasses
import warnings

import pytest

from smalldi import Injector, Provide, SingletonFrozenError
from smalldi.context import InjectionContext, InjectionContextSingletonOverride

pytestmark = pytest.mark.filterwarnings("ignore:Field .* the default is one object shared:UserWarning")


class Bowl:
    def __init__(self, snacks: int = 0):
        self.snacks = snacks


# ---------------------------------------------------------------------------
# Fields: the child's own singleton
# ---------------------------------------------------------------------------

def test_field_registers_unregistered_class_in_child_only():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl

        assert not Injector.is_singleton(Bowl)
        with Injector.context(Fixture) as child:
            assert isinstance(child, InjectionContext)
            assert Injector.is_singleton(Bowl)
            assert Injector.get_instance(Bowl).snacks == 0
        assert not Injector.is_singleton(Bowl)


def test_field_of_registered_class_gives_child_its_own_instance():
    with Injector.context():
        @Injector.singleton
        class Own:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            own: Own

        outer = Injector.get_instance(Own)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Own)
            assert inner is not outer
            assert Injector.get_instance(Own) is inner
        assert Injector.get_instance(Own) is outer


def test_field_lets_child_override_without_reaching_parent():
    """Overriding a SHALLOW-shared singleton leaks to the parent; overriding the child's own doesn't."""
    with Injector.context():
        @Injector.singleton
        class Base:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            base: Base

        with Injector.context(Fixture):
            @Injector.override(Base)
            @Injector.singleton
            class Over(Base):
                pass

            assert type(Injector.get_instance(Base)) is Over
        assert type(Injector.get_instance(Base)) is Base


def test_field_keeps_override_and_shares_clone_between_aliases():
    with Injector.context():
        @Injector.singleton
        class Base:
            pass

        @Injector.override(Base)
        @Injector.singleton
        class Over(Base):
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            base: Base

        outer = Injector.get_instance(Base)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Base)
            assert type(inner) is Over
            assert inner is not outer
            assert Injector.get_instance(Over) is inner


def test_undeclared_singletons_are_shared_with_the_parent():
    with Injector.context():
        @Injector.singleton
        class Shared:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl

        outer = Injector.get_instance(Shared)
        with Injector.context(Fixture):
            assert Injector.get_instance(Shared) is outer


def test_parent_interface_is_rebound_to_the_child_singleton():
    with Injector.context():
        @Injector.interface
        class Water(abc.ABC):
            @abc.abstractmethod
            def drink(self): ...

        @Injector.implements(Water)
        @Injector.singleton
        class TapWater(Water):
            def drink(self):
                return "tap"

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            water: TapWater

        outer = Injector.get_instance(Water)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Water)
            assert inner is not outer
            assert Injector.get_instance(TapWater) is inner
        assert Injector.get_instance(Water) is outer


# ---------------------------------------------------------------------------
# Defaults: preset instances
# ---------------------------------------------------------------------------

def test_default_on_unregistered_class_registers_it_with_the_instance():
    with Injector.context():
        full = Bowl(snacks=7)

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = full

        with Injector.context(Fixture):
            @Injector.inject
            def count(bowl: Provide[Bowl] = None):
                return bowl.snacks

            assert Injector.get_instance(Bowl) is full
            assert count() == 7
        assert not Injector.is_singleton(Bowl)


def test_default_on_registered_class_is_scoped_to_the_block():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        preset = Jar()

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar = preset

        outer = Injector.get_instance(Jar)
        with Injector.context(Fixture):
            assert Injector.get_instance(Jar) is preset
        assert Injector.get_instance(Jar) is outer


def test_default_on_frozen_registered_class_presets_the_child_only():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        preset = Jar()

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar = preset

        outer = Injector.get_instance(Jar)
        with Injector.context(Fixture):
            assert Injector.get_instance(Jar) is preset
        assert Injector.get_instance(Jar) is outer


def test_preset_singleton_is_frozen_in_the_child():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar = Jar()

        with Injector.context(Fixture):
            with pytest.raises(SingletonFrozenError):
                @Injector.override(Jar)
                @Injector.singleton
                class Other(Jar):
                    pass


def test_default_on_implementing_singleton_presets_the_interface_in_the_child():
    with Injector.context():
        @Injector.interface
        class Water(abc.ABC):
            @abc.abstractmethod
            def drink(self): ...

        @Injector.implements(Water)
        @Injector.singleton
        class TapWater(Water):
            def drink(self):
                return "tap"

        class Fake(TapWater):
            def drink(self):
                return "fake"

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            water: TapWater = Fake()

        with Injector.context(Fixture):
            assert Injector.get_instance(Water).drink() == "fake"
            assert Injector.get_instance(TapWater).drink() == "fake"
        assert Injector.get_instance(Water).drink() == "tap"


def test_default_factory_runs_once_per_context_call():
    with Injector.context():
        made = []

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = dataclasses.field(default_factory=lambda: made.append(1) or Bowl(len(made)))

        with Injector.context(Fixture):
            first = Injector.get_instance(Bowl)
        with Injector.context(Fixture):
            second = Injector.get_instance(Bowl)
        assert first is not second
        assert made == [1, 1]


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

def test_plain_class_without_dataclass_decorator_works():
    with Injector.context():
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture):
            assert Injector.get_instance(Bowl).snacks == 3


def test_provide_annotation_is_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Provide[Bowl] = None

        with pytest.raises(TypeError):
            Injector.context(Fixture)


def test_two_fields_of_one_type_are_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            a: Bowl = Bowl(1)
            b: Bowl = Bowl(2)

        with pytest.raises(TypeError):
            Injector.context(Fixture)


def test_non_class_annotation_is_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowls: list[Bowl] = dataclasses.field(default_factory=list)

        with pytest.raises(TypeError):
            Injector.context(Fixture)


def test_two_fields_resolving_to_one_singleton_are_refused_at_enter():
    with Injector.context():
        @Injector.singleton
        class Base:
            pass

        @Injector.override(Base)
        @Injector.singleton
        class Over(Base):
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            base: Base
            over: Over

        manager = Injector.context(Fixture)
        with pytest.raises(TypeError):
            manager.__enter__()
        assert type(Injector.get_instance(Base)) is Over


def test_base_class_itself_is_a_plain_shallow_child():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        with Injector.context(InjectionContextSingletonOverride) as child:
            assert child is Injector.get_context()
            assert Injector.is_singleton(Jar)


# ---------------------------------------------------------------------------
# Injector.context(): the kind, the class and the instance forms
# ---------------------------------------------------------------------------

def test_injector_context_default_kind_is_reset():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        outer = Injector.get_instance(Jar)
        with Injector.context():
            assert Injector.get_instance(Jar) is not outer
        assert Injector.get_instance(Jar) is outer


def test_injector_context_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Injector.context("shallow")


def test_injector_context_accepts_the_class():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture) as child:
            assert child is Injector.get_context()
            assert Injector.get_instance(Bowl).snacks == 3
        assert not Injector.is_singleton(Bowl)


def test_injector_context_accepts_an_instance_with_its_values():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture(bowl=Bowl(9))):
            assert Injector.get_instance(Bowl).snacks == 9
        with Injector.context(Fixture):
            assert Injector.get_instance(Bowl).snacks == 3


def test_none_in_an_instance_presets_nothing():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar | None = None

        outer = Injector.get_instance(Jar)
        with Injector.context(Fixture(jar=None)):
            inner = Injector.get_instance(Jar)
            assert inner is not outer
            assert type(inner) is Jar


def test_instance_form_runs_no_default_factory():
    with Injector.context():
        made = []

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = dataclasses.field(default_factory=lambda: made.append(1) or Bowl(len(made)))

        fixture = Fixture(bowl=Bowl(5))
        with Injector.context(fixture):
            assert Injector.get_instance(Bowl).snacks == 5
        assert made == []


# ---------------------------------------------------------------------------
# apply(context): the child of a given context, unpushed
# ---------------------------------------------------------------------------

def test_apply_derives_the_child_of_a_given_context_without_pushing_it():
    with Injector.context() as outer:
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar
            bowl: Bowl = Bowl(4)

        outer_jar = Injector.get_instance(Jar)
        child = Fixture.apply(outer)
        assert isinstance(child, InjectionContext)
        assert Injector.get_context() is outer
        assert not Injector.is_singleton(Bowl)
        with Injector.foreign_context(child):
            assert Injector.get_instance(Bowl).snacks == 4
            assert Injector.get_instance(Jar) is not outer_jar
        assert Injector.get_instance(Jar) is outer_jar
        assert not Injector.is_singleton(Bowl)


def test_apply_on_an_instance_uses_its_values():
    with Injector.context() as outer:
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(4)

        child = Fixture(bowl=Bowl(8)).apply(outer)
        with Injector.foreign_context(child):
            assert Injector.get_instance(Bowl).snacks == 8


# ---------------------------------------------------------------------------
# Interfaces: refused as fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("registered", [False, True])
def test_plain_field_of_abstract_class_is_refused(registered):
    with Injector.context():
        class Treat(abc.ABC):
            @abc.abstractmethod
            def eat(self): ...

        if registered:
            Injector.interface(Treat)

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            treat: Treat

        with pytest.raises(TypeError):
            Injector.context(Fixture)
        with pytest.raises(TypeError):
            Fixture.apply(Injector.get_context())
        assert Injector.is_interface(Treat) is registered


def test_implemented_interface_is_refused():
    with Injector.context():
        @Injector.interface
        class Treat(abc.ABC):
            @abc.abstractmethod
            def eat(self): ...

        @Injector.implements(Treat)
        @Injector.singleton
        class Cookie(Treat):
            def eat(self):
                return "crunch"

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            treat: Treat

        with pytest.raises(TypeError):
            Injector.context(Fixture)


@pytest.mark.parametrize("registered", [False, True])
def test_preset_on_abstract_class_is_refused_and_touches_nothing(registered):
    with Injector.context():
        class Toy(abc.ABC):
            @abc.abstractmethod
            def squeak(self): ...

        if registered:
            Injector.interface(Toy)

        @Injector.singleton
        class Ball(Toy):
            def squeak(self):
                return "boing"

        if registered:
            Injector.implements(Toy)(Ball)

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            toy: Toy | None = None

        preset = Ball()
        fixture = Fixture(toy=preset)
        with pytest.raises(TypeError):
            Injector.context(fixture)
        with pytest.raises(TypeError):
            fixture.apply(Injector.get_context())
        assert Injector.get_instance(Ball) is not preset


def test_refused_interface_field_is_refused_on_every_call():
    with Injector.context():
        class Treat(abc.ABC):
            @abc.abstractmethod
            def eat(self): ...

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            treat: Treat

        for _ in range(2):
            with pytest.raises(TypeError):
                Injector.context(Fixture)


# ---------------------------------------------------------------------------
# Defaults: the shared-object warning and undecorated subclasses
# ---------------------------------------------------------------------------

SHARED_MESSAGE = "shared by every context"


def test_plain_default_warns_once_per_class():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(3)

        with pytest.warns(UserWarning, match=SHARED_MESSAGE):
            Injector.context(Fixture)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            Injector.context(Fixture)
        assert not [w for w in recorded if SHARED_MESSAGE in str(w.message)]


def test_default_factory_and_none_default_do_not_warn():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = dataclasses.field(default_factory=Bowl)
            jar: Jar | None = None

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            with Injector.context(Fixture):
                assert Injector.get_instance(Bowl).snacks == 0
        assert not [w for w in recorded if SHARED_MESSAGE in str(w.message)]


def test_shared_default_is_one_object_across_contexts():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture):
            first = Injector.get_instance(Bowl)
        with Injector.context(Fixture):
            second = Injector.get_instance(Bowl)
        assert first is second
        assert first.snacks == 3


def test_undecorated_subclass_of_dataclass_fixture_is_refused():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = dataclasses.field(default_factory=lambda: Bowl(6))

        class Child(Fixture):
            pass

        with pytest.raises(TypeError):
            Injector.context(Child)
        with pytest.raises(TypeError):
            Child.apply(Injector.get_context())
        with pytest.raises(TypeError):
            Injector.context(Child())
        assert not Injector.is_singleton(Bowl)

        @dataclasses.dataclass
        class Decorated(Fixture):
            pass

        with Injector.context(Decorated):
            assert Injector.get_instance(Bowl).snacks == 6
