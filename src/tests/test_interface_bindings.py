"""
Specification of interface bindings.

An interface is an `abc.ABC` subclass with an abstract method, registered with
`@Injector.interface`. A singleton binds to it with `@Injector.implements(I)`
or `@Injector.override(I)`; the override wins over the implementation. Bindings
are validated and refused once the interface was injected (frozen).
"""
from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, SingletonFrozenError


def provide(tp):
    """Resolves `tp` the way an injected function does, through `Provide[tp]`."""
    @Injector.inject
    def fn(dep: Provide[tp]):
        return dep

    return fn()


# B1
def test_implementation_is_injected_for_interface(reset_injector):
    """implements(I)(Impl): Provide[I] is Provide[Impl] and Impl is constructed once."""
    built = []

    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(I)
    @Injector.singleton
    class Impl(I):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "impl"

    assert provide(I) is provide(Impl)
    assert type(provide(I)) is Impl
    assert built == [Impl]


# B2
def test_override_is_injected_for_interface(reset_injector):
    """override(J)(JO): Provide[J] is Provide[JO]."""
    @Injector.interface
    class J(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(J)
    @Injector.singleton
    class JO(J):
        def run(self):
            return "override"

    assert provide(J) is provide(JO)
    assert type(provide(J)) is JO


# B2b
def test_conditional_override_false_keeps_interface_implementation(reset_injector):
    """override(I, when=False)(O) does not change I: Provide[I] stays the implementation."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(I)
    @Injector.singleton
    class Impl(I):
        def run(self):
            return "impl"

    @Injector.override(I, when=lambda: False)
    @Injector.singleton
    class O(I):
        def run(self):
            return "override"

    assert type(provide(I)) is Impl
    assert provide(I) is provide(Impl)
    assert provide(I) is not provide(O)


# B3
def test_override_declared_before_implementation_wins(reset_injector):
    """override(K)(KO) then implements(K)(KI): both succeed and Provide[K] is the override instance."""
    @Injector.interface
    class K(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(K)
    @Injector.singleton
    class KO(K):
        def run(self):
            return "override"

    @Injector.implements(K)
    @Injector.singleton
    class KI(K):
        def run(self):
            return "impl"

    assert provide(K) is provide(KO)
    assert type(provide(K)) is KO


# B4
def test_override_declared_after_implementation_wins(reset_injector):
    """implements(K)(KI) then override(K)(KO): Provide[K] is the override and KI is never constructed."""
    built = []

    @Injector.interface
    class K(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(K)
    @Injector.singleton
    class KI(K):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "impl"

    @Injector.override(K)
    @Injector.singleton
    class KO(K):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "override"

    assert provide(K) is provide(KO)
    assert type(provide(K)) is KO
    assert built == [KO]


# B5
def test_interface_override_must_be_registered_singleton(reset_injector):
    """Overriding an interface with a class that is not a registered singleton raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    class O(I):
        def run(self):
            return "o"

    with pytest.raises(TypeError):
        Injector.override(I)(O)


# B6
def test_interface_implementation_must_be_registered_singleton(reset_injector):
    """Implementing an interface with a class that is not a registered singleton raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    class Impl(I):
        def run(self):
            return "impl"

    with pytest.raises(TypeError):
        Injector.implements(I)(Impl)


# B7
def test_interface_override_must_subclass_interface(reset_injector):
    """Overriding an interface with a singleton that doesn't subclass it raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.singleton
    class Unrelated:
        pass

    with pytest.raises(TypeError):
        Injector.override(I)(Unrelated)


# B7
def test_interface_implementation_must_subclass_interface(reset_injector):
    """Implementing an interface with a singleton that doesn't subclass it raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.singleton
    class Unrelated:
        pass

    with pytest.raises(TypeError):
        Injector.implements(I)(Unrelated)


# B8
def test_singleton_override_of_implementation_is_seen_through_interface(reset_injector):
    """implements(M)(MI) then override(MI)(MO): M, MI and MO resolve to one object and MI is never built."""
    built = []

    @Injector.interface
    class M(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(M)
    @Injector.singleton
    class MI(M):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "impl"

    @Injector.override(MI)
    @Injector.singleton
    class MO(MI):
        pass

    mo = provide(MO)
    assert provide(M) is mo
    assert provide(MI) is mo
    assert type(mo) is MO
    assert built == [MO]


# B9
def test_injecting_through_interface_freezes_implementation(reset_injector):
    """implements(N)(NI), inject Provide[N], then override(NI)(NO) raises SingletonFrozenError."""
    @Injector.interface
    class N(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(N)
    @Injector.singleton
    class NI(N):
        def run(self):
            return "impl"

    @Injector.singleton
    class NO(NI):
        pass

    provide(N)

    with pytest.raises(SingletonFrozenError):
        Injector.override(NI)(NO)


# B10
def test_overridden_singleton_cannot_override_interface(reset_injector):
    """override(PO)(PO2) then override(P)(PO) raises TypeError: no chain through an interface."""
    @Injector.interface
    class P(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.singleton
    class PO(P):
        def run(self):
            return "po"

    @Injector.override(PO)
    @Injector.singleton
    class PO2(PO):
        pass

    with pytest.raises(TypeError):
        Injector.override(P)(PO)


# B11
def test_interface_override_cannot_be_overridden(reset_injector):
    """override(Q)(QO) then override(QO)(QO2) raises TypeError: no chain through an interface."""
    @Injector.interface
    class Q(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(Q)
    @Injector.singleton
    class QO(Q):
        def run(self):
            return "qo"

    @Injector.singleton
    class QO2(QO):
        pass

    with pytest.raises(TypeError):
        Injector.override(QO)(QO2)


# B12
def test_implementation_may_be_added_after_overridden_interface_was_injected(reset_injector):
    """override(R)(RO), inject Provide[R], then implements(R)(RI) succeeds and Provide[R] is still RO's instance."""
    @Injector.interface
    class R(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(R)
    @Injector.singleton
    class RO(R):
        def run(self):
            return "ro"

    before = provide(R)

    @Injector.implements(R)
    @Injector.singleton
    class RI(R):
        def run(self):
            return "ri"

    assert provide(R) is before
    assert type(provide(R)) is RO


# B13
def test_injected_interface_cannot_be_overridden(reset_injector):
    """Once Provide[R] was injected, override(R)(...) raises SingletonFrozenError."""
    @Injector.interface
    class R(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(R)
    @Injector.singleton
    class RI(R):
        def run(self):
            return "ri"

    @Injector.singleton
    class RO(R):
        def run(self):
            return "ro"

    provide(R)

    with pytest.raises(SingletonFrozenError):
        Injector.override(R)(RO)


# B14
def test_interface_without_bindings_raises_runtime_error(reset_injector):
    """An interface with neither implementation nor override resolves to RuntimeError."""
    @Injector.interface
    class R(ABC):
        @abstractmethod
        def run(self):
            pass

    with pytest.raises(RuntimeError) as excinfo:
        provide(R)
    assert not isinstance(excinfo.value, RecursionError)


# B14
def test_failed_resolve_freezes_interface_against_implementation(reset_injector):
    """A failed resolve of an unbound interface freezes it: a later implements raises SingletonFrozenError."""
    @Injector.interface
    class R(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.singleton
    class RI(R):
        def run(self):
            return "ri"

    with pytest.raises(RuntimeError):
        provide(R)

    with pytest.raises(SingletonFrozenError):
        Injector.implements(R)(RI)


# B15
def test_second_implementation_is_rejected_and_first_stays(reset_injector):
    """implements(S)(A) then implements(S)(B) raises RuntimeError and Provide[S] is still A's instance."""
    @Injector.interface
    class S(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(S)
    @Injector.singleton
    class A(S):
        def run(self):
            return "a"

    @Injector.singleton
    class B(S):
        def run(self):
            return "b"

    with pytest.raises(RuntimeError):
        Injector.implements(S)(B)

    assert provide(S) is provide(A)
    assert type(provide(S)) is A


# B16
def test_second_interface_override_is_rejected_and_first_stays(reset_injector):
    """override(T)(X) then override(T)(Y) raises TypeError and Provide[T] is still X's instance."""
    @Injector.interface
    class T(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(T)
    @Injector.singleton
    class X(T):
        def run(self):
            return "x"

    @Injector.singleton
    class Y(T):
        def run(self):
            return "y"

    with pytest.raises(TypeError):
        Injector.override(T)(Y)

    assert provide(T) is provide(X)
    assert type(provide(T)) is X


# B17
def test_implementation_cannot_also_be_override(reset_injector):
    """implements(I)(X) then override(I)(X) raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(I)
    @Injector.singleton
    class X(I):
        def run(self):
            return "x"

    with pytest.raises(TypeError):
        Injector.override(I)(X)


# B17
def test_override_cannot_also_be_implementation(reset_injector):
    """override(I)(X) then implements(I)(X) raises TypeError."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(I)
    @Injector.singleton
    class X(I):
        def run(self):
            return "x"

    with pytest.raises(TypeError):
        Injector.implements(I)(X)


# B18
def test_failed_override_keeps_implementation_binding(reset_injector):
    """A rejected override (non-singleton) leaves the implementation bound: Provide[I] is still its instance."""
    built = []

    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(I)
    @Injector.singleton
    class Impl(I):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "impl"

    class NotRegistered(I):
        def run(self):
            return "nope"

    with pytest.raises(TypeError):
        Injector.override(I)(NotRegistered)

    assert provide(I) is provide(Impl)
    assert type(provide(I)) is Impl
    assert built == [Impl]


# B18
def test_failed_implementation_keeps_override_binding(reset_injector):
    """A rejected implementation (not a subclass) leaves the override bound: Provide[I] is still its instance."""
    built = []

    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.override(I)
    @Injector.singleton
    class O(I):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "o"

    @Injector.singleton
    class Unrelated:
        def __init__(self):
            built.append(type(self))

    with pytest.raises(TypeError):
        Injector.implements(I)(Unrelated)

    assert provide(I) is provide(O)
    assert type(provide(I)) is O
    assert built == [O]


# B18
def test_failed_chain_through_interface_keeps_singleton_override(reset_injector):
    """A rejected override(P)(PO) after override(PO)(PO2) leaves P unbound and PO resolving to PO2's instance."""
    built = []

    @Injector.interface
    class P(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.singleton
    class PO(P):
        def __init__(self):
            built.append(type(self))

        def run(self):
            return "po"

    @Injector.override(PO)
    @Injector.singleton
    class PO2(PO):
        pass

    with pytest.raises(TypeError):
        Injector.override(P)(PO)

    with pytest.raises(RuntimeError):
        provide(P)
    assert provide(PO) is provide(PO2)
    assert type(provide(PO)) is PO2
    assert built == [PO2]


# B19
def test_injected_function_resolves_binding_added_after_decoration(reset_injector):
    """A function injecting an unbound interface works once a binding is added before its first call."""
    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.inject
    def use(dep: Provide[I]):
        return dep

    @Injector.implements(I)
    @Injector.singleton
    class Impl(I):
        def run(self):
            return "impl"

    result = use()
    assert type(result) is Impl
    assert result is provide(Impl)
