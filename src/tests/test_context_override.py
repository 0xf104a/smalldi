"""
Specification of `InjectionContextSingletonOverride` and `CopyOf[T]`.

A dataclass subclass declares a `SHALLOW` child context field by field: a
plain class is made injectable, `CopyOf[T]` gives the child its own copy of
`T`, and a default value becomes the instance of `T`, on the shared singleton
or on the copy. Every test opens its own outer RESET context and registers
all of its classes inside it, so the root context is never touched.
"""
import abc
import dataclasses

import pytest

from smalldi import Injector, Provide, SingletonFrozenError
from smalldi.context import InjectionContext, InjectionContextSingletonOverride, CopyOf


class Bowl:
    def __init__(self, snacks: int = 0):
        self.snacks = snacks


# ---------------------------------------------------------------------------
# Plain fields: made injectable
# ---------------------------------------------------------------------------

def test_plain_field_registers_unregistered_class_in_child_only():
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


def test_plain_field_registers_abstract_class_as_interface():
    with Injector.context():
        class Treat(abc.ABC):
            @abc.abstractmethod
            def eat(self): ...

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            treat: Treat

        with Injector.context(Fixture):
            assert Injector.is_interface(Treat)

            @Injector.implements(Treat)
            @Injector.singleton
            class Cookie(Treat):
                def eat(self):
                    return "crunch"

            assert Injector.get_instance(Treat).eat() == "crunch"
        assert not Injector.is_interface(Treat)


def test_plain_field_of_registered_class_shares_parent_singleton():
    with Injector.context():
        @Injector.singleton
        class Shared:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            shared: Shared

        outer = Injector.get_instance(Shared)
        with Injector.context(Fixture):
            assert Injector.get_instance(Shared) is outer


# ---------------------------------------------------------------------------
# CopyOf[T]: the child's own singleton
# ---------------------------------------------------------------------------

def test_copy_of_gives_child_its_own_instance():
    with Injector.context():
        @Injector.singleton
        class Own:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            own: CopyOf[Own]

        outer = Injector.get_instance(Own)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Own)
            assert inner is not outer
            assert Injector.get_instance(Own) is inner
        assert Injector.get_instance(Own) is outer


def test_copy_of_lets_child_override_without_reaching_parent():
    """Overriding a SHALLOW-shared singleton leaks to the parent; overriding a copy doesn't."""
    with Injector.context():
        @Injector.singleton
        class Base:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            base: CopyOf[Base]

        with Injector.context(Fixture):
            @Injector.override(Base)
            @Injector.singleton
            class Over(Base):
                pass

            assert type(Injector.get_instance(Base)) is Over
        assert type(Injector.get_instance(Base)) is Base


def test_copy_of_keeps_override_and_shares_copy_between_aliases():
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
            base: CopyOf[Base]

        outer = Injector.get_instance(Base)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Base)
            assert type(inner) is Over
            assert inner is not outer
            assert Injector.get_instance(Over) is inner


def test_copy_of_interface_copies_the_singleton_it_resolves_to():
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
            water: CopyOf[Water]

        outer = Injector.get_instance(Water)
        with Injector.context(Fixture):
            inner = Injector.get_instance(Water)
            assert inner is not outer
            assert Injector.get_instance(TapWater) is inner
        assert Injector.get_instance(Water) is outer


def test_copy_of_unregistered_class_is_refused_at_enter():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: CopyOf[Bowl]

        manager = Injector.context(Fixture)
        with pytest.raises(TypeError):
            manager.__enter__()
        assert not Injector.is_singleton(Bowl)


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


def test_default_on_shared_singleton_reaches_the_parent():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        preset = Jar()

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: Jar = preset

        with Injector.context(Fixture):
            assert Injector.get_instance(Jar) is preset
        assert Injector.get_instance(Jar) is preset


def test_default_on_frozen_shared_singleton_is_refused_before_anything_changes():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl
            jar: Jar = Jar()

        outer = Injector.get_instance(Jar)
        manager = Injector.context(Fixture)
        with pytest.raises(SingletonFrozenError):
            manager.__enter__()
        assert Injector.get_instance(Jar) is outer
        assert not Injector.is_singleton(Bowl)


def test_default_on_copy_is_scoped_to_the_block():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        preset = Jar()

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: CopyOf[Jar] = preset

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
            jar: CopyOf[Jar] = Jar()

        with Injector.context(Fixture):
            with pytest.raises(SingletonFrozenError):
                @Injector.override(Jar)
                @Injector.singleton
                class Other(Jar):
                    pass


def test_default_on_interface_presets_the_singleton_it_resolves_to():
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

        class Fake(Water):
            def drink(self):
                return "fake"

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            water: CopyOf[Water] = Fake()

        with Injector.context(Fixture):
            assert Injector.get_instance(Water).drink() == "fake"
            assert Injector.get_instance(TapWater).drink() == "fake"
        assert Injector.get_instance(Water).drink() == "tap"


def test_default_on_unregistered_interface_registers_and_binds_it():
    with Injector.context():
        class Water(abc.ABC):
            @abc.abstractmethod
            def drink(self): ...

        class Fake(Water):
            def drink(self):
                return "fake"

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            water: Water = Fake()

        with Injector.context(Fixture):
            assert Injector.is_interface(Water)
            assert Injector.get_instance(Water).drink() == "fake"


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


def test_unbound_interface_default_is_refused():
    with Injector.context():
        @Injector.interface
        class Water(abc.ABC):
            @abc.abstractmethod
            def drink(self): ...

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            water: Water = object()

        with pytest.raises(TypeError):
            Injector.context(Fixture).__enter__()


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


def test_an_instance_passed_to_context_uses_its_values():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        preset = Jar()

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: CopyOf[Jar]

        outer = Injector.get_instance(Jar)
        with Injector.context(Fixture(jar=preset)):
            assert Injector.get_instance(Jar) is preset
        assert Injector.get_instance(Jar) is outer


def test_none_in_an_instance_presets_nothing():
    with Injector.context():
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: CopyOf[Jar] | None = None

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
            base: CopyOf[Base]
            over: CopyOf[Over]

        with pytest.raises(TypeError):
            Injector.context(Fixture).__enter__()


def test_apply_derives_the_child_of_a_given_context_without_pushing_it():
    with Injector.context() as outer:
        @Injector.singleton
        class Jar:
            pass

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            jar: CopyOf[Jar]
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
