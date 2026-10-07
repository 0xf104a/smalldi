"""
Specification of singleton overrides.

`@Injector.override(S)` above `@Injector.singleton` on a subclass `T` makes
`Provide[S]` resolve to the instance of `T`. Overrides are validated, are not
transitive, and are refused once the target was injected (frozen).
"""
import pytest

from smalldi import Injector, Provide, SingletonFrozenError


def provide(tp):
    """Resolves `tp` the way an injected function does, through `Provide[tp]`."""
    @Injector.inject
    def fn(dep: Provide[tp]):
        return dep

    return fn()


# A1
def test_override_makes_target_resolve_to_override_instance(reset_injector):
    """override(S)(T): Provide[S] and Provide[T] are one object and S is never constructed."""
    built = []

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))

    @Injector.override(S)
    @Injector.singleton
    class T(S):
        pass

    assert provide(S) is provide(T)
    assert type(provide(S)) is T
    assert built == [T]


# A2
def test_override_reuses_already_injected_override_instance(reset_injector):
    """override(S)(T) after T was injected: Provide[S] is that T instance and T is built once."""
    built = []

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class T(S):
        pass

    existing = provide(T)
    Injector.override(S)(T)

    assert provide(S) is existing
    assert built == [T]


# A3
def test_override_class_must_be_registered_singleton(reset_injector):
    """Overriding with a class that is not a registered singleton raises TypeError."""
    @Injector.singleton
    class S:
        pass

    class T(S):
        pass

    with pytest.raises(TypeError):
        Injector.override(S)(T)


# A4
def test_override_class_must_subclass_target(reset_injector):
    """Overriding with a singleton that does not subclass the target raises TypeError."""
    @Injector.singleton
    class S:
        pass

    @Injector.singleton
    class Unrelated:
        pass

    with pytest.raises(TypeError):
        Injector.override(S)(Unrelated)


# A5
def test_override_target_must_be_registered_singleton(reset_injector):
    """Overriding a class that is not a registered singleton raises TypeError."""
    class S:
        pass

    @Injector.singleton
    class T(S):
        pass

    with pytest.raises(TypeError):
        Injector.override(S)(T)


# A6
def test_singleton_cannot_override_itself(reset_injector):
    """override(A)(A) raises TypeError."""
    @Injector.singleton
    class A:
        pass

    with pytest.raises(TypeError):
        Injector.override(A)(A)


# A7
def test_second_override_of_same_target_is_rejected_and_first_stays(reset_injector):
    """A second override of one target raises and the first override keeps being injected."""
    built = []

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))

    @Injector.override(S)
    @Injector.singleton
    class T1(S):
        pass

    @Injector.singleton
    class T2(S):
        pass

    with pytest.raises((TypeError, RuntimeError)):
        Injector.override(S)(T2)

    assert provide(S) is provide(T1)
    assert type(provide(S)) is T1
    assert built == [T1]


# A8
def test_override_chain_forward_order_is_rejected(reset_injector):
    """override(S1)(S2) then override(S2)(S3) raises TypeError: overrides are not transitive."""
    @Injector.singleton
    class S1:
        pass

    @Injector.override(S1)
    @Injector.singleton
    class S2(S1):
        pass

    @Injector.singleton
    class S3(S2):
        pass

    with pytest.raises(TypeError):
        Injector.override(S2)(S3)


# A9
def test_override_chain_reverse_order_is_rejected(reset_injector):
    """override(R2)(R3) then override(R1)(R2) raises TypeError: an override can't be overridden."""
    @Injector.singleton
    class R1:
        pass

    @Injector.singleton
    class R2(R1):
        pass

    @Injector.override(R2)
    @Injector.singleton
    class R3(R2):
        pass

    with pytest.raises(TypeError):
        Injector.override(R1)(R2)


# A10
def test_one_class_may_override_two_targets(reset_injector):
    """override(S1)(U) and override(S2)(U) with U subclassing both: all three resolve to one object."""
    built = []

    @Injector.singleton
    class S1:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class S2:
        def __init__(self):
            built.append(type(self))

    @Injector.override(S1)
    @Injector.override(S2)
    @Injector.singleton
    class U(S1, S2):
        def __init__(self):
            built.append(type(self))

    u = provide(U)
    assert provide(S1) is u
    assert provide(S2) is u
    assert built == [U]


# A11
def test_override_after_target_injected_raises_frozen_error(reset_injector):
    """Overriding a singleton that was already injected raises SingletonFrozenError."""
    @Injector.singleton
    class S:
        pass

    @Injector.singleton
    class T(S):
        pass

    provide(S)

    with pytest.raises(SingletonFrozenError):
        Injector.override(S)(T)


# A12
def test_failed_subclass_check_leaves_both_singletons_untouched(reset_injector):
    """After a rejected override, target and candidate still resolve to their own, distinct instances."""
    built = []

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class Unrelated:
        def __init__(self):
            built.append(type(self))

    with pytest.raises(TypeError):
        Injector.override(S)(Unrelated)

    s = provide(S)
    other = provide(Unrelated)
    assert type(s) is S
    assert type(other) is Unrelated
    assert s is not other
    assert sorted(built, key=lambda cls: cls.__name__) == [S, Unrelated]


# A12
def test_failed_chain_leaves_existing_override_in_place(reset_injector):
    """After a rejected chain override, S1 still resolves to S2's instance and S3 stays separate."""
    built = []

    @Injector.singleton
    class S1:
        def __init__(self):
            built.append(type(self))

    @Injector.override(S1)
    @Injector.singleton
    class S2(S1):
        pass

    @Injector.singleton
    class S3(S2):
        pass

    with pytest.raises(TypeError):
        Injector.override(S2)(S3)

    s2 = provide(S2)
    assert provide(S1) is s2
    assert type(s2) is S2
    assert type(provide(S3)) is S3
    assert provide(S3) is not s2
    assert built == [S2, S3]


# A12
def test_failed_override_of_frozen_target_keeps_injected_instance(reset_injector):
    """After a rejected override of a frozen singleton, the previously injected instance is still returned."""
    built = []

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class T(S):
        pass

    before = provide(S)
    with pytest.raises(SingletonFrozenError):
        Injector.override(S)(T)

    assert provide(S) is before
    assert built == [S]


# A13
def test_injecting_through_override_freezes_target(reset_injector):
    """Injecting Provide[S] where S is overridden by T freezes S: a further override raises SingletonFrozenError."""
    @Injector.singleton
    class S:
        pass

    @Injector.override(S)
    @Injector.singleton
    class T(S):
        pass

    @Injector.singleton
    class X(S):
        pass

    provide(S)

    with pytest.raises(SingletonFrozenError):
        Injector.override(S)(X)


# A14
def test_same_thread_circular_dependency_raises_runtime_error(reset_injector):
    """A injects B and B injects A in their constructors: resolving A raises RuntimeError, not RecursionError."""
    @Injector.singleton
    class A:
        def __init__(self):
            @Injector.inject
            def need(b: Provide[B]):
                return b

            self.b = need()

    @Injector.singleton
    class B:
        def __init__(self):
            @Injector.inject
            def need(a: Provide[A]):
                return a

            self.a = need()

    with pytest.raises(RuntimeError) as excinfo:
        provide(A)
    assert not isinstance(excinfo.value, RecursionError)


# A15
def test_circular_dependency_through_override_raises_runtime_error(reset_injector):
    """override(S)(T) where T's constructor injects S: resolving S raises RuntimeError, not RecursionError."""
    @Injector.singleton
    class S:
        pass

    @Injector.override(S)
    @Injector.singleton
    class T(S):
        def __init__(self):
            @Injector.inject
            def need(s: Provide[S]):
                return s

            self.s = need()

    with pytest.raises(RuntimeError) as excinfo:
        provide(S)
    assert not isinstance(excinfo.value, RecursionError)


# A16
def test_failing_constructor_still_freezes_singleton(reset_injector):
    """A constructor that raises freezes the singleton: a subsequent override raises SingletonFrozenError."""
    class BootError(Exception):
        pass

    @Injector.singleton
    class S:
        def __init__(self):
            raise BootError("boot failed")

    @Injector.singleton
    class T(S):
        def __init__(self):
            pass

    with pytest.raises(BootError):
        provide(S)

    with pytest.raises(SingletonFrozenError):
        Injector.override(S)(T)
