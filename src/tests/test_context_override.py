"""
Specification of `InjectionContextOverride`, the declared context.

A dataclass subclass declares a `SHALLOW` child context field by field: every
declared class gets a singleton of its own in the child, a clone of the parent's
singleton for a registered class and a registration in the child only for an
unregistered one, and a default value becomes the instance of that singleton.
A field `n: ImplementationOf[I]` gives the child a binding of its own for the
interface `I`: unbound without a value, so the block implements or overrides it;
with a value, an instance of `I`, bound to it and frozen. The value is held by
a singleton of the binding alone: its class is not registered by the preset, so
several interface fields may hold instances of one class, or one object, and a
value that is no instance of `I` raises `TypeError` from `Injector.context`.
`Injector.context` takes the subclass, with its defaults, or an instance of it,
with its attributes; `apply(context)` derives the child of a given context
without pushing it. A plain abstract class is refused as a field, as is
`ImplementationOf[C]` with a concrete `C`. `InjectionContextSingletonOverride`
is the deprecated alias of the base class, in `smalldi.context` and in `smalldi`.
Every test opens its own outer RESET context and registers all of its classes
inside it, so the root context is never touched.
"""
import abc
import dataclasses
import warnings
from typing import Annotated, Optional, get_args, get_origin
from unittest.mock import MagicMock, Mock, create_autospec

import pytest

import smalldi
import smalldi.context
from smalldi import ImplementationOf, Injector, Provide, SingletonFrozenError
from smalldi.context import InjectionContext, InjectionContextOverride, InjectionSubcontextType

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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
            water: TapWater = Fake()

        with Injector.context(Fixture):
            assert Injector.get_instance(Water).drink() == "fake"
            assert Injector.get_instance(TapWater).drink() == "fake"
        assert Injector.get_instance(Water).drink() == "tap"


def test_default_factory_runs_once_per_context_call():
    with Injector.context():
        made = []

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture):
            assert Injector.get_instance(Bowl).snacks == 3


def test_provide_annotation_is_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            bowl: Provide[Bowl] = None

        with pytest.raises(TypeError):
            Injector.context(Fixture)


def test_two_fields_of_one_type_are_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            a: Bowl = Bowl(1)
            b: Bowl = Bowl(2)

        with pytest.raises(TypeError):
            Injector.context(Fixture)


def test_non_class_annotation_is_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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

        with Injector.context(InjectionContextOverride) as child:
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
        class Fixture(InjectionContextOverride):
            bowl: Bowl = Bowl(3)

        with Injector.context(Fixture) as child:
            assert child is Injector.get_context()
            assert Injector.get_instance(Bowl).snacks == 3
        assert not Injector.is_singleton(Bowl)


def test_injector_context_accepts_an_instance_with_its_values():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
            bowl: Bowl = Bowl(4)

        child = Fixture(bowl=Bowl(8)).apply(outer)
        with Injector.foreign_context(child):
            assert Injector.get_instance(Bowl).snacks == 8


# ---------------------------------------------------------------------------
# Interfaces: plain abstract fields are refused
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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
        class Fixture(InjectionContextOverride):
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


# ---------------------------------------------------------------------------
# Interfaces: ImplementationOf[I]
# ---------------------------------------------------------------------------

class Treat(abc.ABC):
    @abc.abstractmethod
    def eat(self): ...


class Cookie(Treat):
    def eat(self):
        return "crunch"


class Fake(Treat):
    def eat(self):
        return "fake"


def _bind_cookie():
    """Registers Treat as an interface implemented by the singleton Cookie, in the current context."""
    Injector.interface(Treat)
    Injector.implements(Treat)(Injector.singleton(Cookie))


def test_field_starts_unbound_in_the_child():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        outer = Injector.get_instance(Treat)
        with Injector.context(Fixture):
            assert Injector.is_interface(Treat)
            assert Injector.get_instance(Cookie) is outer
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
        assert Injector.get_instance(Treat) is outer


def test_lets_the_block_implement_an_inherited_interface():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        with Injector.context(Fixture):
            @Injector.implements(Treat)
            @Injector.singleton
            class Biscuit(Treat):
                def eat(self):
                    return "snap"

            @Injector.inject
            def eat(treat: Provide[Treat] = None):
                return treat.eat()

            assert eat() == "snap"
            assert Injector.get_instance(Treat) is Injector.get_instance(Biscuit)
        assert type(Injector.get_instance(Treat)) is Cookie
        assert not Injector.is_singleton(Biscuit)


def test_lets_the_block_override_a_frozen_parent_interface():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        outer = Injector.get_instance(Treat)
        with Injector.context(Fixture):
            @Injector.override(Treat)
            @Injector.singleton
            class Biscuit(Treat):
                def eat(self):
                    return "snap"

            assert type(Injector.get_instance(Treat)) is Biscuit
        assert Injector.get_instance(Treat) is outer


def test_drops_the_parent_override():
    with Injector.context():
        _bind_cookie()

        @Injector.override(Treat)
        @Injector.singleton
        class Biscuit(Treat):
            def eat(self):
                return "snap"

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        with Injector.context(Fixture):
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
        assert type(Injector.get_instance(Treat)) is Biscuit


def test_requested_before_binding_freezes_the_block_binding():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        with Injector.context(Fixture):
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
            with pytest.raises(SingletonFrozenError):
                @Injector.implements(Treat)
                @Injector.singleton
                class Biscuit(Treat):
                    def eat(self):
                        return "snap"


def test_does_not_freeze_an_unrequested_parent_binding():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        with Injector.context(Fixture):
            @Injector.implements(Treat)
            @Injector.singleton
            class Biscuit(Treat):
                def eat(self):
                    return "snap"

            assert type(Injector.get_instance(Treat)) is Biscuit

        @Injector.override(Treat)
        @Injector.singleton
        class Choc(Treat):
            def eat(self):
                return "melt"

        assert type(Injector.get_instance(Treat)) is Choc


def test_binding_an_inherited_singleton_marks_the_shared_object():
    """Documented SHALLOW caveat: an undeclared singleton bound in the block is the parent's object."""
    with Injector.context():
        _bind_cookie()

        @Injector.singleton
        class Biscuit(Treat):
            def eat(self):
                return "snap"

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]

        with Injector.context(Fixture):
            Injector.override(Treat)(Biscuit)
            assert type(Injector.get_instance(Treat)) is Biscuit
        assert type(Injector.get_instance(Treat)) is Cookie
        with pytest.raises(SingletonFrozenError):
            @Injector.override(Biscuit)
            @Injector.singleton
            class Sub(Biscuit):
                pass


@pytest.mark.parametrize("preset", [False, True])
def test_registers_unregistered_interface_in_child_only(preset):
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        assert not Injector.is_interface(Treat)
        fake = Fake()
        with Injector.context(Fixture(treat=fake) if preset else Fixture):
            assert Injector.is_interface(Treat)
            if preset:
                assert Injector.get_instance(Treat) is fake
            else:
                with pytest.raises(RuntimeError, match="not implemented"):
                    Injector.get_instance(Treat)
        assert not Injector.is_interface(Treat)
        assert not Injector.is_singleton(Fake)


def test_with_instance_presets_the_interface_without_registering_its_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            @Injector.inject
            def eat(treat: Provide[Treat] = None):
                return treat

            assert Injector.get_instance(Treat) is fake
            assert eat() is fake
            assert not Injector.is_singleton(Fake)
            with pytest.raises(KeyError):
                Injector.get_instance(Fake)
            with pytest.raises(TypeError):
                @Injector.inject
                def fake_(fake_: Provide[Fake] = None):
                    return fake_
        assert not Injector.is_singleton(Fake)
        assert type(Injector.get_instance(Treat)) is Cookie


def test_with_instance_of_registered_class_leaves_the_class_to_the_parent():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        outer = Injector.get_instance(Treat)
        preset = Cookie()
        with Injector.context(Fixture(treat=preset)):
            @Injector.inject
            def both(treat: Provide[Treat] = None, cookie: Provide[Cookie] = None):
                return treat, cookie

            assert Injector.get_instance(Treat) is preset
            assert Injector.get_instance(Cookie) is outer
            assert both() == (preset, outer)
        assert Injector.get_instance(Treat) is outer
        assert Injector.get_instance(Cookie) is outer


def test_with_instance_keeps_other_implementing_class_untouched():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        outer = Injector.get_instance(Cookie)
        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            assert Injector.get_instance(Treat) is fake
            assert Injector.get_instance(Cookie) is outer
        assert Injector.get_instance(Treat) is outer
        assert Injector.get_instance(Cookie) is outer


def test_with_instance_of_overriding_class_leaves_the_aliases_to_the_parent():
    with Injector.context():
        _bind_cookie()

        @Injector.override(Cookie)
        @Injector.singleton
        class Choc(Cookie):
            def eat(self):
                return "melt"

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        outer = Injector.get_instance(Treat)
        assert type(outer) is Choc
        preset = Choc()
        with Injector.context(Fixture(treat=preset)):
            assert Injector.get_instance(Treat) is preset
            assert Injector.get_instance(Cookie) is outer
            assert Injector.get_instance(Choc) is outer
        assert Injector.get_instance(Treat) is outer
        assert Injector.get_instance(Cookie) is outer
        assert Injector.get_instance(Choc) is outer


def test_two_interface_fields_may_hold_two_instances_of_one_class():
    with Injector.context():
        _bind_cookie()

        @Injector.interface
        class Toy(abc.ABC):
            @abc.abstractmethod
            def squeak(self): ...

        class Both(Treat, Toy):
            def eat(self):
                return "fake"

            def squeak(self):
                return "fake"

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None
            toy: ImplementationOf[Toy] | None = None

        first, second = Both(), Both()
        with Injector.context(Fixture(treat=first, toy=second)):
            assert Injector.get_instance(Treat) is first
            assert Injector.get_instance(Toy) is second
            assert not Injector.is_singleton(Both)
        assert type(Injector.get_instance(Treat)) is Cookie
        with pytest.raises(RuntimeError, match="not implemented"):
            Injector.get_instance(Toy)


def test_two_interface_fields_may_hold_one_object():
    with Injector.context():
        _bind_cookie()

        @Injector.interface
        class Toy(abc.ABC):
            @abc.abstractmethod
            def squeak(self): ...

        class Both(Treat, Toy):
            def eat(self):
                return "fake"

            def squeak(self):
                return "fake"

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None
            toy: ImplementationOf[Toy] | None = None

        both = Both()
        with Injector.context(Fixture(treat=both, toy=both)):
            assert Injector.get_instance(Treat) is both
            assert Injector.get_instance(Toy) is both
            assert not Injector.is_singleton(Both)
        assert type(Injector.get_instance(Treat)) is Cookie


def test_preset_class_is_not_registered_when_the_parent_does_not_know_it():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        with Injector.context(Fixture(treat=Fake())):
            assert not Injector.is_singleton(Fake)
            with pytest.raises(KeyError):
                Injector.get_instance(Fake)
        assert not Injector.is_singleton(Fake)


def test_preset_class_resolves_to_the_parent_singleton_when_the_parent_knows_it():
    with Injector.context():
        _bind_cookie()
        Injector.singleton(Fake)

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        outer_fake = Injector.get_instance(Fake)
        preset = Fake()
        with Injector.context(Fixture(treat=preset)):
            @Injector.inject
            def fake_(fake_: Provide[Fake] = None):
                return fake_

            assert Injector.is_singleton(Fake)
            assert Injector.get_instance(Treat) is preset
            assert Injector.get_instance(Fake) is outer_fake
            assert fake_() is outer_fake
        assert Injector.get_instance(Fake) is outer_fake


def test_concrete_field_and_interface_field_may_hold_one_object():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None
            fake: Fake | None = None

        fake = Fake()
        with Injector.context(Fixture(treat=fake, fake=fake)):
            @Injector.inject
            def both(treat: Provide[Treat] = None, fake_: Provide[Fake] = None):
                return treat, fake_

            assert Injector.get_instance(Treat) is fake
            assert Injector.get_instance(Fake) is fake
            assert both() == (fake, fake)
        assert not Injector.is_singleton(Fake)
        assert type(Injector.get_instance(Treat)) is Cookie


def test_concrete_field_and_interface_field_may_hold_two_instances_of_one_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None
            cookie: Cookie | None = None

        outer = Injector.get_instance(Cookie)
        for_treat, for_cookie = Cookie(), Cookie()
        with Injector.context(Fixture(treat=for_treat, cookie=for_cookie)):
            assert Injector.get_instance(Treat) is for_treat
            assert Injector.get_instance(Cookie) is for_cookie
        assert Injector.get_instance(Treat) is outer
        assert Injector.get_instance(Cookie) is outer


def test_preset_is_frozen_in_the_child():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        with Injector.context(Fixture(treat=Fake())):
            with pytest.raises(SingletonFrozenError):
                @Injector.override(Treat)
                @Injector.singleton
                class Biscuit(Treat):
                    def eat(self):
                        return "snap"

            with pytest.raises(RuntimeError, match="already implemented"):
                @Injector.implements(Treat)
                @Injector.singleton
                class Wafer(Treat):
                    def eat(self):
                        return "crisp"


@pytest.mark.parametrize("mock", [
    lambda: Mock(spec=Treat),
    lambda: MagicMock(spec=Treat),
    lambda: create_autospec(Treat, instance=True),
], ids=["Mock", "MagicMock", "create_autospec"])
def test_mock_with_spec_is_accepted_as_a_preset(mock):
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        treat = mock()
        treat.eat.return_value = "mocked"
        with Injector.context(Fixture(treat=treat)):
            @Injector.inject
            def eat(treat: Provide[Treat] = None):
                return treat.eat()

            assert Injector.get_instance(Treat) is treat
            assert eat() == "mocked"
            assert not Injector.is_singleton(type(treat))
        assert type(Injector.get_instance(Treat)) is Cookie


def test_mocks_with_spec_may_share_a_class_across_interface_fields():
    with Injector.context():
        _bind_cookie()

        @Injector.interface
        class Toy(abc.ABC):
            @abc.abstractmethod
            def squeak(self): ...

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None
            toy: ImplementationOf[Toy] | None = None

        treat, toy = MagicMock(spec=Treat), MagicMock(spec=Toy)
        with Injector.context(Fixture(treat=treat, toy=toy)):
            assert Injector.get_instance(Treat) is treat
            assert Injector.get_instance(Toy) is toy
            assert not Injector.is_singleton(type(treat))
        assert type(Injector.get_instance(Treat)) is Cookie


NOT_AN_INSTANCE = "not an instance of Treat"


def _bad_presets():
    return [
        pytest.param("a string", id="str"),
        pytest.param(Fake, id="class"),
        pytest.param(MagicMock(), id="bare-mock"),
    ]


@pytest.mark.parametrize("bad", _bad_presets())
def test_non_instance_preset_is_refused_in_the_instance_form(bad):
    with Injector.context() as outer:
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        fixture = Fixture(treat=bad)
        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            Injector.context(fixture)
        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            fixture.apply(outer)
        assert Injector.get_context() is outer
        assert type(Injector.get_instance(Treat)) is Cookie


@pytest.mark.parametrize("bad", _bad_presets())
def test_non_instance_default_is_refused_in_the_class_form(bad):
    with Injector.context() as outer:
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] = bad

        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            Injector.context(Fixture)
        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            Fixture.apply(outer)
        assert Injector.get_context() is outer
        assert not Injector.is_interface(Treat)


def test_non_instance_from_default_factory_is_refused_in_the_class_form():
    with Injector.context() as outer:
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] = dataclasses.field(default_factory=MagicMock)

        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            Injector.context(Fixture)
        with pytest.raises(TypeError, match=NOT_AN_INSTANCE):
            Fixture.apply(outer)
        assert Injector.get_context() is outer
        assert not Injector.is_interface(Treat)


def test_instance_form_and_none_preset_nothing():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = Fake()

        outer = Injector.get_instance(Treat)
        with Injector.context(Fixture(treat=None)):
            assert Injector.is_interface(Treat)
            assert not Injector.is_singleton(Fake)
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
        assert Injector.get_instance(Treat) is outer


@pytest.mark.parametrize("annotation", [
    ImplementationOf[Treat] | None,
    Optional[ImplementationOf[Treat]],
    ImplementationOf[Treat | None],
], ids=["union-none", "Optional", "inner-none"])
def test_optional_spellings_declare_the_interface(annotation):
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: annotation = None

        outer = Injector.get_instance(Treat)
        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            assert Injector.get_instance(Treat) is fake
        with Injector.context(Fixture):
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
        assert Injector.get_instance(Treat) is outer


def test_implementation_of_default_factory_runs_once_per_context_call():
    with Injector.context():
        _bind_cookie()
        made = []

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] = dataclasses.field(default_factory=lambda: made.append(1) or Fake())

        with Injector.context(Fixture):
            first = Injector.get_instance(Treat)
        with Injector.context(Fixture):
            second = Injector.get_instance(Treat)
        assert type(first) is type(second) is Fake
        assert first is not second
        assert made == [1, 1]


def test_implementation_of_plain_default_warns_once_per_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] = Fake()

        with pytest.warns(UserWarning, match=SHARED_MESSAGE):
            Injector.context(Fixture)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            with Injector.context(Fixture):
                first = Injector.get_instance(Treat)
            with Injector.context(Fixture):
                second = Injector.get_instance(Treat)
        assert not [w for w in recorded if SHARED_MESSAGE in str(w.message)]
        assert first is second


def test_with_implementing_class_field():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat]
            cookie: Cookie

        outer = Injector.get_instance(Treat)
        with Injector.context(Fixture):
            Injector.implements(Treat)(Cookie)
            inner = Injector.get_instance(Treat)
            assert type(inner) is Cookie
            assert inner is not outer
            assert Injector.get_instance(Cookie) is inner
        assert Injector.get_instance(Treat) is outer
        assert Injector.get_instance(Cookie) is outer


def test_nested_declared_context_resolves_to_the_preset():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        @dataclasses.dataclass
        class Nested(InjectionContextOverride):
            bowl: Bowl

        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            with Injector.context(Nested):
                assert Injector.get_instance(Treat) is fake
                assert not Injector.is_singleton(Fake)
            assert Injector.get_instance(Treat) is fake
        assert type(Injector.get_instance(Treat)) is Cookie


def test_nested_shallow_context_resolves_to_the_preset():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            with Injector.context(InjectionSubcontextType.SHALLOW):
                assert Injector.get_instance(Treat) is fake
                assert not Injector.is_singleton(Fake)
            with Injector.context(InjectionSubcontextType.SHALLOW):
                # the nested child's binding is a new, unfrozen one: it may override Treat
                @Injector.override(Treat)
                @Injector.singleton
                class Biscuit(Treat):
                    def eat(self):
                        return "snap"

                assert type(Injector.get_instance(Treat)) is Biscuit
            assert Injector.get_instance(Treat) is fake
        assert type(Injector.get_instance(Treat)) is Cookie


def test_nested_reset_context_builds_a_new_instance_of_the_preset_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            with Injector.context(InjectionSubcontextType.RESET):
                inner = Injector.get_instance(Treat)
                assert type(inner) is Fake
                assert inner is not fake
                assert Injector.get_instance(Treat) is inner
                assert not Injector.is_singleton(Fake)
            assert Injector.get_instance(Treat) is fake
        assert type(Injector.get_instance(Treat)) is Cookie


def test_nested_stack_context_builds_a_new_instance_of_the_preset_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        fake = Fake()
        with Injector.context(Fixture(treat=fake)):
            with Injector.context(InjectionSubcontextType.STACK):
                inner = Injector.get_instance(Treat)
                assert type(inner) is Fake
                assert inner is not fake
                assert Injector.get_instance(Treat) is inner
                assert not Injector.is_singleton(Fake)
            assert Injector.get_instance(Treat) is fake
        assert type(Injector.get_instance(Treat)) is Cookie


def test_nested_stack_context_lets_the_block_override_the_preset_class():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        with Injector.context(Fixture(treat=Fake())):
            with Injector.context(InjectionSubcontextType.STACK):
                @Injector.override(Treat)
                @Injector.singleton
                class Biscuit(Treat):
                    def eat(self):
                        return "snap"

                assert type(Injector.get_instance(Treat)) is Biscuit


def test_parent_binding_is_unchanged_after_the_block():
    with Injector.context():
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        with Injector.context(Fixture(treat=Fake())):
            assert type(Injector.get_instance(Treat)) is Fake
        # the parent's binding was neither requested nor frozen: it still accepts an override
        @Injector.override(Treat)
        @Injector.singleton
        class Biscuit(Treat):
            def eat(self):
                return "snap"

        assert type(Injector.get_instance(Treat)) is Biscuit


def test_apply_with_implementation_of_derives_the_binding_unpushed():
    with Injector.context() as outer:
        _bind_cookie()

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat] | None = None

        outer_treat = Injector.get_instance(Treat)
        fake = Fake()
        preset = Fixture(treat=fake).apply(outer)
        unbound = Fixture.apply(outer)
        assert isinstance(preset, InjectionContext)
        assert Injector.get_context() is outer
        assert not Injector.is_singleton(Fake)
        assert Injector.get_instance(Treat) is outer_treat
        with Injector.foreign_context(preset):
            assert Injector.get_instance(Treat) is fake
            assert not Injector.is_singleton(Fake)
        with Injector.foreign_context(unbound):
            with pytest.raises(RuntimeError, match="not implemented"):
                Injector.get_instance(Treat)
        assert Injector.get_instance(Treat) is outer_treat
        assert not Injector.is_singleton(Fake)


def test_implementation_of_concrete_class_is_refused():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Cookie]

        for _ in range(2):
            with pytest.raises(TypeError, match="concrete"):
                Injector.context(Fixture)
            with pytest.raises(TypeError, match="concrete"):
                Fixture.apply(Injector.get_context())
        assert not Injector.is_singleton(Cookie)
        assert not Injector.is_interface(Cookie)


def test_provide_around_implementation_of_is_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Outside(InjectionContextOverride):
            treat: Provide[ImplementationOf[Treat]] = None

        @dataclasses.dataclass
        class Inside(InjectionContextOverride):
            treat: ImplementationOf[Provide[Treat]] = None

        for fixture in (Outside, Inside):
            with pytest.raises(TypeError, match="Provide"):
                Injector.context(fixture)
        assert not Injector.is_interface(Treat)


def test_two_fields_declaring_one_interface_are_rejected():
    with Injector.context():
        @dataclasses.dataclass
        class Twice(InjectionContextOverride):
            a: ImplementationOf[Treat] | None = None
            b: ImplementationOf[Treat] | None = None

        @dataclasses.dataclass
        class Mixed(InjectionContextOverride):
            a: ImplementationOf[Treat] | None = None
            b: Treat | None = None

        with pytest.raises(TypeError, match="both declare"):
            Injector.context(Twice)
        with pytest.raises(TypeError, match="abstract"):  # the plain abstract field is refused first
            Injector.context(Mixed)
        assert not Injector.is_interface(Treat)


def test_plain_abstract_field_refusal_names_implementation_of():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: Treat

        with pytest.raises(TypeError, match="ImplementationOf"):
            Injector.context(Fixture)


def test_interface_field_with_a_union_is_refused_naming_implementation_of():
    with Injector.context():
        class Toy(abc.ABC):
            @abc.abstractmethod
            def squeak(self): ...

        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[Treat | Toy] | None = None

        with pytest.raises(TypeError, match=r"declare the interface as treat: ImplementationOf\[I\]"):
            Injector.context(Fixture)
        assert not Injector.is_interface(Treat)


def test_interface_field_with_a_generic_alias_is_refused_naming_implementation_of():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            treat: ImplementationOf[list[int]] | None = None

        with pytest.raises(TypeError, match=r"declare the interface as treat: ImplementationOf\[I\]"):
            Injector.context(Fixture)


def test_plain_field_with_a_generic_alias_is_refused_naming_a_singleton():
    with Injector.context():
        @dataclasses.dataclass
        class Fixture(InjectionContextOverride):
            bowls: list[int] | None = None

        with pytest.raises(TypeError, match="declare a singleton as T") as info:
            Injector.context(Fixture)
        assert "ImplementationOf" not in str(info.value)


def test_implementation_of_is_exported_from_smalldi():
    assert "ImplementationOf" in smalldi.__all__
    assert smalldi.ImplementationOf is ImplementationOf
    assert get_origin(ImplementationOf[Treat]) is Annotated
    assert get_args(ImplementationOf[Treat])[0] is Treat


# ---------------------------------------------------------------------------
# Deprecated name
# ---------------------------------------------------------------------------

def test_deprecated_name_warns_and_is_the_same_class():
    with Injector.context():
        with pytest.warns(DeprecationWarning, match="InjectionContextOverride"):
            from smalldi.context import InjectionContextSingletonOverride
        assert InjectionContextSingletonOverride is InjectionContextOverride
        with pytest.warns(DeprecationWarning, match="1.0.0"):
            fetched = getattr(smalldi.context, "InjectionContextSingletonOverride")
        assert fetched is InjectionContextOverride

        @dataclasses.dataclass
        class Fixture(InjectionContextSingletonOverride):
            bowl: Bowl = dataclasses.field(default_factory=lambda: Bowl(2))

        with Injector.context(Fixture):
            assert Injector.get_instance(Bowl).snacks == 2
        assert not Injector.is_singleton(Bowl)


def test_deprecated_name_imports_from_the_package():
    with pytest.warns(DeprecationWarning, match="InjectionContextOverride") as recorded:
        from smalldi import InjectionContextSingletonOverride
    assert InjectionContextSingletonOverride is InjectionContextOverride
    assert recorded[0].filename == __file__
    for _ in range(2):  # every access warns: the name is not cached in the package
        with pytest.warns(DeprecationWarning, match="1.0.0") as recorded:
            fetched = smalldi.InjectionContextSingletonOverride
        assert fetched is InjectionContextOverride
        assert recorded[0].filename == __file__
    assert "InjectionContextSingletonOverride" not in vars(smalldi)
    assert "InjectionContextSingletonOverride" not in smalldi.__all__


def test_deprecated_package_name_warns_with_the_module_message():
    with pytest.warns(DeprecationWarning) as from_package:
        getattr(smalldi, "InjectionContextSingletonOverride")
    with pytest.warns(DeprecationWarning) as from_module:
        getattr(smalldi.context, "InjectionContextSingletonOverride")
    assert str(from_package[0].message) == str(from_module[0].message)


def test_new_names_do_not_warn():
    with Injector.context():
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            import smalldi as package
            import smalldi.context as module
            from smalldi.context import InjectionContextOverride as Base
            from smalldi import ImplementationOf as Marker
            assert Base is module.InjectionContextOverride
            assert Marker is package.ImplementationOf
            assert package.InjectionContextOverride is Base
        assert not [w for w in recorded if issubclass(w.category, DeprecationWarning)]
        assert "InjectionContextSingletonOverride" not in vars(smalldi.context)
        assert "InjectionContextSingletonOverride" not in vars(smalldi)
