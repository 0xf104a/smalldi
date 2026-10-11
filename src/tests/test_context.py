"""
Specification of injection subcontexts: RESET and STACK.

`with Injector.context(kind):` pushes a child context on the injector and the
exit pops it. A RESET child keeps every registration and every binding of its
parent but creates fresh, unfrozen singletons. A STACK child turns each
effective binding (the override where there is one) into the new base, so the
child may override it again. Neither child leaks instances or bindings into
its parent.

Every test opens its own outer RESET context and registers all of its classes
inside it, so the root context is never touched.
"""
import abc

import pytest

from smalldi import Injector, Provide, SingletonFrozenError
from smalldi.context import InjectionSubcontextType


def _base_and_override():
    """Registers `Base` and its override `Over` in the current context."""
    @Injector.singleton
    class Base:
        pass

    @Injector.override(Base)
    @Injector.singleton
    class Over(Base):
        pass

    return Base, Over


# ---------------------------------------------------------------------------
# RESET
# ---------------------------------------------------------------------------

def test_R1_reset_keeps_singleton_override():
    """Base overridden by Over in the parent: inside RESET, Base still resolves to Over."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.RESET):
            assert type(Injector.get_instance(Base)) is Over


def test_R2_reset_target_and_override_share_one_instance():
    """Inside RESET, Base and Over resolve to the same object."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.RESET):
            assert Injector.get_instance(Base) is Injector.get_instance(Over)


def test_R3_reset_creates_fresh_instances():
    """An instance created in the parent is not reused by the RESET child."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()
        parent_instance = Injector.get_instance(Base)

        with Injector.context(InjectionSubcontextType.RESET):
            inner_instance = Injector.get_instance(Base)
            assert type(inner_instance) is Over
            assert inner_instance is not parent_instance


def test_R4_reset_keeps_override_non_transitive():
    """Inside RESET, Over is still an override, so it can't be overridden itself."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.RESET):
            with pytest.raises(TypeError):
                @Injector.override(Over)
                @Injector.singleton
                class OverOver(Over):
                    pass


def test_R5_reset_keeps_target_overridden():
    """Inside RESET, Base is still overridden, so a second override of it is refused."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.RESET):
            with pytest.raises(RuntimeError):
                @Injector.override(Base)
                @Injector.singleton
                class Over2(Base):
                    pass


def test_R6_reset_unfreezes_singletons():
    """A singleton frozen in the parent accepts an override inside RESET."""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.singleton
        class C:
            pass

        assert type(Injector.get_instance(C)) is C  # freezes C in the parent

        with Injector.context(InjectionSubcontextType.RESET):
            try:
                @Injector.override(C)
                @Injector.singleton
                class COver(C):
                    pass
            except SingletonFrozenError as exc:
                pytest.fail(f"RESET child must not inherit the frozen state: {exc!r}")

            assert type(Injector.get_instance(C)) is COver


def test_R7_reset_override_does_not_leak_into_parent():
    """An override declared inside RESET leaves the parent's binding and instance untouched."""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.singleton
        class C:
            pass

        parent_instance = Injector.get_instance(C)

        with Injector.context(InjectionSubcontextType.RESET):
            @Injector.override(C)
            @Injector.singleton
            class COver(C):
                pass

            assert type(Injector.get_instance(C)) is COver

        after = Injector.get_instance(C)
        assert type(after) is C
        assert after is parent_instance


def test_R9_reset_keeps_one_instance_for_multi_target_override():
    """O overrides B1 and B2: inside RESET, B1, B2 and O resolve to one fresh instance of O."""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.singleton
        class B1:
            pass

        @Injector.singleton
        class B2:
            pass

        @Injector.override(B2)
        @Injector.override(B1)
        @Injector.singleton
        class O(B1, B2):
            pass

        parent_instance = Injector.get_instance(O)

        with Injector.context(InjectionSubcontextType.RESET):
            b1 = Injector.get_instance(B1)
            b2 = Injector.get_instance(B2)
            o = Injector.get_instance(O)
            assert b1 is b2
            assert b2 is o
            assert type(o) is O
            assert o is not parent_instance


def test_R8_reset_keeps_interface_override():
    """Interface control case: an interface override set in the parent is seen inside RESET."""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.interface
        class I(abc.ABC):
            @abc.abstractmethod
            def run(self):
                ...

        @Injector.implements(I)
        @Injector.singleton
        class Impl(I):
            def run(self):
                return "impl"

        @Injector.override(I)
        @Injector.singleton
        class IOver(Impl):
            def run(self):
                return "over"

        with Injector.context(InjectionSubcontextType.RESET):
            assert type(Injector.get_instance(I)) is IOver


# ---------------------------------------------------------------------------
# STACK
# ---------------------------------------------------------------------------

def test_S1_stack_resolves_target_to_override():
    """Base overridden by Over in the parent: inside STACK, Base resolves to Over."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.STACK):
            assert type(Injector.get_instance(Base)) is Over


def test_S2_stack_target_and_override_share_one_instance():
    """Inside STACK, Base and Over resolve to the same object."""
    # Design decision: shared instance; flip to `is not` if decided otherwise.
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.STACK):
            assert Injector.get_instance(Base) is Injector.get_instance(Over)


def test_S3_stack_makes_override_the_new_base():
    """Inside STACK, Base counts as unoverridden: a new override of it succeeds and wins."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.STACK):
            @Injector.override(Base)
            @Injector.singleton
            class Over2(Over):
                pass

            assert type(Injector.get_instance(Base)) is Over2


def test_S4_stack_override_does_not_leak_into_parent():
    """An override declared inside STACK is gone after the child exits."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        with Injector.context(InjectionSubcontextType.STACK):
            @Injector.override(Base)
            @Injector.singleton
            class Over2(Over):
                pass

            assert type(Injector.get_instance(Base)) is Over2

        assert type(Injector.get_instance(Base)) is Over


def test_S5_stack_makes_interface_override_the_new_implementation():
    """Interface control case: inside STACK the interface resolves to IOver and accepts a new override."""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.interface
        class I(abc.ABC):
            @abc.abstractmethod
            def run(self):
                ...

        @Injector.implements(I)
        @Injector.singleton
        class Impl(I):
            def run(self):
                return "impl"

        @Injector.override(I)
        @Injector.singleton
        class IOver(Impl):
            def run(self):
                return "over"

        with Injector.context(InjectionSubcontextType.STACK):
            assert type(Injector.get_instance(I)) is IOver

        # Requesting the instance freezes the interface, so the new override
        # goes into a sibling STACK child that hasn't resolved `I` yet.
        with Injector.context(InjectionSubcontextType.STACK):
            @Injector.override(I)
            @Injector.singleton
            class IOver2(IOver):
                def run(self):
                    return "over2"

            assert type(Injector.get_instance(I)) is IOver2


# ---------------------------------------------------------------------------
# Injected functions called from inside a child context
# ---------------------------------------------------------------------------

def test_X1_reset_injected_function_receives_override():
    """A function injected in the parent, called inside RESET, receives an instance of Over."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        @Injector.inject
        def use(dep: Provide[Base]):
            return dep

        with Injector.context(InjectionSubcontextType.RESET):
            assert type(use()) is Over


def test_X1_stack_injected_function_receives_override():
    """A function injected in the parent, called inside STACK, receives an instance of Over."""
    with Injector.context(InjectionSubcontextType.RESET):
        Base, Over = _base_and_override()

        @Injector.inject
        def use(dep: Provide[Base]):
            return dep

        with Injector.context(InjectionSubcontextType.STACK):
            assert type(use()) is Over
