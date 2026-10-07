"""
Concurrency specification of `Injector`.

Singletons are constructed exactly once under contention, bindings racing a
first injection are linearizable, conflicting registrations let at most one
winner through, and constructors may wait for other threads or resolve other
singletons without deadlocking the injector.

Every thread is a daemon and every wait has a timeout, so a deadlock fails the
test instead of hanging the run. Each concurrency test is additionally run in
a bounded worker thread: a lock left behind by a deadlocked thread of an
earlier test then fails the next test fast instead of blocking it.
"""
import threading
import time
from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, SingletonFrozenError
from smalldi.container import Container

TIMEOUT = 2.0
ITERATIONS = 50
N = 16
SLOW = 0.01
# Upper bound for one whole test body; only reached if something hangs outside a race.
BODY_TIMEOUT = 20.0


def provide(tp):
    """Resolves `tp` the way an injected function does, through `Provide[tp]`."""
    @Injector.inject
    def fn(dep: Provide[tp]):
        return dep

    return fn()


def run_bounded(fn, timeout, message):
    """Runs `fn` in a daemon thread and fails with `message` if it doesn't finish in `timeout`."""
    outcome = []

    def target():
        try:
            outcome.append(("ok", fn()))
        except BaseException as exc:
            outcome.append(("error", exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), message
    kind, result = outcome[0]
    if kind == "error":
        raise result
    return result


def bounded(test):
    """Runs a test body in a bounded thread, after probing that the injector isn't locked by a stuck thread."""
    def wrapper(reset_injector):
        run_bounded(
            lambda: Injector.is_singleton(object), TIMEOUT,
            f"deadlock: injector is still locked by a thread of an earlier test after {TIMEOUT}s",
        )
        run_bounded(
            lambda: test(reset_injector), BODY_TIMEOUT,
            f"deadlock: test body still running after {BODY_TIMEOUT}s",
        )

    wrapper.__name__ = test.__name__
    wrapper.__qualname__ = test.__qualname__
    wrapper.__doc__ = test.__doc__
    return wrapper


def run_concurrently(*callables, timeout=TIMEOUT):
    """
    Runs each callable in its own daemon thread, released together by a barrier.

    Returns one `(kind, value)` per callable: `("ok", result)` or
    `("error", exception)`. Fails with "deadlock: threads still alive" if any
    thread hasn't finished within `timeout`.
    """
    count = len(callables)
    barrier = threading.Barrier(count)
    results = [None] * count

    def guarded(index, fn):
        def target():
            try:
                barrier.wait(timeout)
                results[index] = ("ok", fn())
            except BaseException as exc:
                results[index] = ("error", exc)

        return target

    threads = [
        threading.Thread(target=guarded(index, fn), daemon=True)
        for index, fn in enumerate(callables)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    alive = [index for index, thread in enumerate(threads) if thread.is_alive()]
    assert not alive, f"deadlock: threads still alive after {timeout}s: {alive}"
    assert all(result is not None for result in results)
    return results


def succeeded(result):
    return result[0] == "ok"


def value(result):
    """Unwraps a successful result; fails on an exception."""
    assert succeeded(result), f"unexpected exception: {result[1]!r}"
    return result[1]


def error(result):
    """Unwraps a failed result; fails on a success."""
    assert not succeeded(result), f"expected an exception, got {result[1]!r}"
    return result[1]


def is_cycle_error(exc):
    return isinstance(exc, RuntimeError) and not isinstance(exc, RecursionError)


# ---------------------------------------------------------------------------
# Exactly-once construction
# ---------------------------------------------------------------------------

# C1
@bounded
def test_concurrent_get_instance_constructs_singleton_once(reset_injector):
    """N threads resolving one singleton at once share one instance, constructed exactly once."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.singleton
        class S:
            def __init__(self):
                built.append(self)
                time.sleep(SLOW)

        results = run_concurrently(*[lambda: Injector.get_instance(S) for _i in range(N)])
        instances = [value(result) for result in results]

        assert len(built) == 1, f"constructed {len(built)} times"
        assert all(instance is built[0] for instance in instances)


# C2
@bounded
def test_concurrent_interface_and_class_resolution_constructs_once(reset_injector):
    """8 threads resolving Provide[I] and 8 resolving Provide[Impl] get one Impl, constructed once."""
    for _ in range(ITERATIONS):
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
                built.append(self)
                time.sleep(SLOW)

            def run(self):
                return "impl"

        @Injector.inject
        def via_interface(dep: Provide[I]):
            return dep

        @Injector.inject
        def via_class(dep: Provide[Impl]):
            return dep

        results = run_concurrently(*([via_interface] * 8 + [via_class] * 8))
        instances = [value(result) for result in results]

        assert len(built) == 1, f"constructed {len(built)} times"
        assert all(instance is built[0] for instance in instances)


# C3
@bounded
def test_concurrent_resolution_through_override_constructs_override_once(reset_injector):
    """Mixed get_instance(S) and get_instance(T) with override(S)(T): T built once, S never."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.singleton
        class S:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)

        @Injector.override(S)
        @Injector.singleton
        class T(S):
            pass

        callables = [lambda: Injector.get_instance(S) for _i in range(8)]
        callables += [lambda: Injector.get_instance(T) for _i in range(8)]
        results = run_concurrently(*callables)
        instances = [value(result) for result in results]

        assert built == [T], f"constructed: {built}"
        assert all(type(instance) is T for instance in instances)
        assert all(instance is instances[0] for instance in instances)


# ---------------------------------------------------------------------------
# Override vs. first injection races (linearizability)
# ---------------------------------------------------------------------------

# C4
@bounded
def test_override_racing_first_injection_is_linearizable(reset_injector):
    """override(S)(T) racing get_instance(S): either the override wins and T is handed out, or it's frozen and S is."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.singleton
        class S:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)

        @Injector.singleton
        class T(S):
            pass

        override_result, get_result = run_concurrently(
            lambda: Injector.override(S)(T),
            lambda: Injector.get_instance(S),
        )
        instance = value(get_result)

        if succeeded(override_result):
            assert type(instance) is T, "override succeeded but S instance handed out"
            assert built == [T], f"constructed: {built}"
        else:
            assert isinstance(error(override_result), SingletonFrozenError)
            assert type(instance) is S, "override was refused but T instance handed out"
            assert built == [S], f"constructed: {built}"
        assert provide(S) is instance


# C5
@bounded
def test_interface_override_racing_first_injection_is_linearizable(reset_injector):
    """override(I)(O) racing get_instance(I) with implementation Impl: either O or Impl is handed out, consistently."""
    for _ in range(ITERATIONS):
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
                time.sleep(SLOW)

            def run(self):
                return "impl"

        @Injector.singleton
        class O(I):
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)

            def run(self):
                return "override"

        override_result, get_result = run_concurrently(
            lambda: Injector.override(I)(O),
            lambda: Injector.get_instance(I),
        )
        instance = value(get_result)

        if succeeded(override_result):
            assert type(instance) is O, "override succeeded but Impl instance handed out"
            assert built == [O], f"constructed: {built}"
        else:
            assert isinstance(error(override_result), SingletonFrozenError)
            assert type(instance) is Impl, "override was refused but O instance handed out"
            assert built == [Impl], f"constructed: {built}"
        assert provide(I) is instance


# C6
@bounded
def test_implementation_override_racing_interface_injection_is_linearizable(reset_injector):
    """override(Impl)(O2) racing get_instance(I) where Impl implements I: either O2 or Impl is handed out."""
    for _ in range(ITERATIONS):
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
                time.sleep(SLOW)

            def run(self):
                return "impl"

        @Injector.singleton
        class O2(Impl):
            pass

        override_result, get_result = run_concurrently(
            lambda: Injector.override(Impl)(O2),
            lambda: Injector.get_instance(I),
        )
        instance = value(get_result)

        if succeeded(override_result):
            assert type(instance) is O2, "override succeeded but Impl instance handed out"
            assert built == [O2], f"constructed: {built}"
        else:
            assert isinstance(error(override_result), SingletonFrozenError)
            assert type(instance) is Impl, "override was refused but O2 instance handed out"
            assert built == [Impl], f"constructed: {built}"
        assert provide(I) is instance
        assert provide(Impl) is instance


# ---------------------------------------------------------------------------
# Concurrent conflicting registrations
# ---------------------------------------------------------------------------

# C7
@bounded
def test_concurrent_overrides_of_one_target_have_one_winner(reset_injector):
    """override(S)(T1) racing override(S)(T2): exactly one succeeds and Provide[S] is the winner's instance."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.singleton
        class S:
            def __init__(self):
                built.append(type(self))

        @Injector.singleton
        class T1(S):
            pass

        @Injector.singleton
        class T2(S):
            pass

        result1, result2 = run_concurrently(
            lambda: Injector.override(S)(T1),
            lambda: Injector.override(S)(T2),
        )
        outcomes = [(T1, result1), (T2, result2)]
        winners = [cls for cls, result in outcomes if succeeded(result)]
        losers = [result for _cls, result in outcomes if not succeeded(result)]

        assert len(winners) == 1, f"{len(winners)} overrides succeeded"
        assert isinstance(error(losers[0]), (TypeError, RuntimeError))
        winner = winners[0]
        assert provide(S) is provide(winner)
        assert type(provide(S)) is winner
        assert built == [winner]


# C8
@bounded
def test_concurrent_chain_overrides_never_both_succeed(reset_injector):
    """override(S1)(S2) racing override(S2)(S3): at most one succeeds, the other raises TypeError."""
    for _ in range(ITERATIONS):
        @Injector.singleton
        class S1:
            pass

        @Injector.singleton
        class S2(S1):
            pass

        @Injector.singleton
        class S3(S2):
            pass

        results = run_concurrently(
            lambda: Injector.override(S1)(S2),
            lambda: Injector.override(S2)(S3),
        )
        successes = [result for result in results if succeeded(result)]
        failures = [result for result in results if not succeeded(result)]

        assert len(successes) <= 1, "both overrides succeeded: chain formed under race"
        for failure in failures:
            assert isinstance(error(failure), TypeError)


# C9
@bounded
def test_concurrent_chain_through_interface_never_both_succeed(reset_injector):
    """override(I)(X) racing override(X)(Y): at most one succeeds, the other raises TypeError."""
    for _ in range(ITERATIONS):
        @Injector.interface
        class I(ABC):
            @abstractmethod
            def run(self):
                pass

        @Injector.singleton
        class X(I):
            def run(self):
                return "x"

        @Injector.singleton
        class Y(X):
            pass

        results = run_concurrently(
            lambda: Injector.override(I)(X),
            lambda: Injector.override(X)(Y),
        )
        successes = [result for result in results if succeeded(result)]
        failures = [result for result in results if not succeeded(result)]

        assert len(successes) <= 1, "both overrides succeeded: chain formed under race"
        for failure in failures:
            assert isinstance(error(failure), TypeError)


# C10
@bounded
def test_concurrent_implementations_of_one_interface_have_one_winner(reset_injector):
    """implements(I)(A) racing implements(I)(B): exactly one succeeds and Provide[I] is the winner's instance."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.interface
        class I(ABC):
            @abstractmethod
            def run(self):
                pass

        @Injector.singleton
        class A(I):
            def __init__(self):
                built.append(type(self))

            def run(self):
                return "a"

        @Injector.singleton
        class B(I):
            def __init__(self):
                built.append(type(self))

            def run(self):
                return "b"

        result_a, result_b = run_concurrently(
            lambda: Injector.implements(I)(A),
            lambda: Injector.implements(I)(B),
        )
        outcomes = [(A, result_a), (B, result_b)]
        winners = [cls for cls, result in outcomes if succeeded(result)]
        losers = [result for _cls, result in outcomes if not succeeded(result)]

        assert len(winners) == 1, f"{len(winners)} implementations succeeded"
        assert isinstance(error(losers[0]), RuntimeError)
        winner = winners[0]
        assert provide(I) is provide(winner)
        assert type(provide(I)) is winner
        assert built == [winner]


# C11
@bounded
def test_concurrent_registration_and_resolution_of_distinct_singletons(reset_injector):
    """N threads each registering and resolving their own singleton: no errors, each built once, identities match."""
    workers = 8
    for _ in range(ITERATIONS):
        built = []

        def worker():
            @Injector.singleton
            class Own:
                def __init__(self):
                    built.append(type(self))
                    time.sleep(SLOW)

            return Own, Injector.get_instance(Own)

        results = run_concurrently(*[worker for _i in range(workers)])
        pairs = [value(result) for result in results]

        classes = [cls for cls, _instance in pairs]
        assert len(set(classes)) == workers
        assert sorted(built, key=id) == sorted(classes, key=id), f"constructed: {built}"
        for cls, instance in pairs:
            assert type(instance) is cls
            assert Injector.get_instance(cls) is instance


# ---------------------------------------------------------------------------
# Deadlock and re-entrancy
# ---------------------------------------------------------------------------

# C12
@pytest.mark.skip(reason="Known limitation: dependency cycles spanning several threads are not detected and may deadlock. Opt-in detection is planned.")
@bounded
def test_cross_thread_circular_dependency_does_not_deadlock(reset_injector):
    """A needs B and B needs A, resolved from two threads at once: both finish and at least one gets RuntimeError."""
    for _ in range(ITERATIONS):
        @Injector.singleton
        class A:
            def __init__(self):
                time.sleep(SLOW)
                self.b = Injector.get_instance(B)

        @Injector.singleton
        class B:
            def __init__(self):
                time.sleep(SLOW)
                self.a = Injector.get_instance(A)

        results = run_concurrently(
            lambda: Injector.get_instance(A),
            lambda: Injector.get_instance(B),
        )
        failures = [error(result) for result in results if not succeeded(result)]

        assert failures, "no thread detected the cycle"
        for exc in failures:
            assert is_cycle_error(exc), f"expected RuntimeError, got {exc!r}"


# C13
@bounded
def test_constructor_can_wait_for_another_thread_resolving_a_singleton(reset_injector):
    """E's constructor joins a thread resolving unrelated D: E finishes in time and the thread got D's instance."""
    built = []

    @Injector.singleton
    class D:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class E:
        def __init__(self):
            outcome = []

            def helper():
                try:
                    outcome.append(("ok", Injector.get_instance(D)))
                except BaseException as exc:
                    outcome.append(("error", exc))

            thread = threading.Thread(target=helper, daemon=True)
            thread.start()
            thread.join(TIMEOUT / 2)
            self.helper_finished = not thread.is_alive()
            self.helper_outcome = list(outcome)
            built.append(type(self))

    (result,) = run_concurrently(lambda: Injector.get_instance(E))
    e = value(result)

    assert e.helper_finished, "deadlock: helper thread could not resolve D while E's constructor waited for it"
    assert e.helper_outcome and succeeded(e.helper_outcome[0]), f"helper outcome: {e.helper_outcome}"
    d = value(e.helper_outcome[0])
    assert type(d) is D
    assert Injector.get_instance(D) is d
    assert sorted(built, key=lambda cls: cls.__name__) == [D, E]


# C14
@bounded
def test_nested_resolution_under_concurrent_resolution_of_dependencies(reset_injector):
    """A needs B needs C while other threads resolve C and B: no deadlock, each built once, identities consistent."""
    for _ in range(ITERATIONS):
        built = []

        @Injector.singleton
        class C:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)

        @Injector.singleton
        class B:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)
                self.c = Injector.get_instance(C)

        @Injector.singleton
        class A:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)
                self.b = Injector.get_instance(B)

        result_a, result_c, result_b = run_concurrently(
            lambda: Injector.get_instance(A),
            lambda: Injector.get_instance(C),
            lambda: Injector.get_instance(B),
        )
        a, c, b = value(result_a), value(result_c), value(result_b)

        assert sorted(built, key=lambda cls: cls.__name__) == [A, B, C], f"constructed: {built}"
        assert type(a) is A and type(b) is B and type(c) is C
        assert a.b is b
        assert b.c is c
        assert Injector.get_instance(A) is a


# C15
@bounded
def test_failing_constructor_under_contention_never_leaks_partial_instance(reset_injector):
    """S's constructor fails once; 8 threads resolve S: each gets an exception or one fully built S, never None."""
    class BootError(Exception):
        pass

    for _ in range(ITERATIONS):
        calls = []
        calls_lock = threading.Lock()

        @Injector.singleton
        class S:
            def __init__(self):
                with calls_lock:
                    calls.append(1)
                    first = len(calls) == 1
                time.sleep(SLOW)
                if first:
                    raise BootError("first construction fails")
                self.ready = True

        results = run_concurrently(*[lambda: Injector.get_instance(S) for _i in range(8)])

        instances = []
        for result in results:
            if succeeded(result):
                instance = result[1]
                assert instance is not None, "None handed out"
                assert type(instance) is S
                assert getattr(instance, "ready", False) is True, "partially initialized S handed out"
                instances.append(instance)
            else:
                assert isinstance(result[1], Exception), f"non-exception failure: {result[1]!r}"
        assert all(instance is instances[0] for instance in instances)


# Regression: acyclic resolution through an interface and a singleton from two threads
@bounded
def test_acyclic_interface_and_singleton_resolution_does_not_deadlock(reset_injector):
    """Impl needs J (another interface) in its constructor; resolving Impl and I from two threads shares one Impl."""
    built = []

    @Injector.interface
    class J(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(J)
    @Injector.singleton
    class JImpl(J):
        def run(self):
            return "j"

    @Injector.interface
    class I(ABC):
        @abstractmethod
        def run(self):
            pass

    @Injector.implements(I)
    @Injector.singleton
    class Impl(I):
        @Injector.inject
        def __init__(self, j: Provide[J] = None):
            built.append(type(self))
            time.sleep(SLOW * 20)
            self.j = j

        def run(self):
            return "impl"

    def resolve_interface_later():
        time.sleep(SLOW * 5)
        return Injector.get_instance(I)

    result_impl, result_iface = run_concurrently(
        lambda: Injector.get_instance(Impl),
        resolve_interface_later,
    )
    impl = value(result_impl)
    assert value(result_iface) is impl
    assert type(impl) is Impl
    assert type(impl.j) is JImpl
    assert built == [Impl]


# Regression: override attempted while the target's constructor is running
@bounded
def test_override_while_target_is_being_constructed_does_not_deadlock(reset_injector):
    """override(S)(X) while S is being constructed raises SingletonFrozenError; S's instance is an S."""
    started = threading.Event()
    release = threading.Event()
    built = []

    @Injector.singleton
    class D:
        def __init__(self):
            built.append(type(self))

    @Injector.singleton
    class S:
        def __init__(self):
            built.append(type(self))
            started.set()
            release.wait(TIMEOUT / 2)
            self.d = Injector.get_instance(D)

    @Injector.singleton
    class X(S):
        pass

    def resolve_s():
        return Injector.get_instance(S)

    def override_s_once_started():
        assert started.wait(TIMEOUT / 2), "S's constructor did not start"
        try:
            return Injector.override(S)(X)
        finally:
            release.set()

    result_s, result_override = run_concurrently(resolve_s, override_s_once_started)
    release.set()

    assert isinstance(error(result_override), SingletonFrozenError)
    s = value(result_s)
    assert type(s) is S
    assert type(s.d) is D
    assert built == [S, D]
    assert Injector.get_instance(S) is s


# ---------------------------------------------------------------------------
# Stress / mixed operations
# ---------------------------------------------------------------------------

# C16
@bounded
def test_mixed_resolutions_and_registrations_stay_consistent(reset_injector):
    """Resolving I, Impl and S while overriding S and implementing J concurrently ends in a consistent state."""
    for _ in range(ITERATIONS):
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
                time.sleep(SLOW)

            def run(self):
                return "impl"

        @Injector.interface
        class J(ABC):
            @abstractmethod
            def run(self):
                pass

        @Injector.singleton
        class JImpl(J):
            def __init__(self):
                built.append(type(self))

            def run(self):
                return "jimpl"

        @Injector.singleton
        class S:
            def __init__(self):
                built.append(type(self))
                time.sleep(SLOW)

        @Injector.singleton
        class T(S):
            pass

        result_i, result_impl, result_s, result_override, result_implements = run_concurrently(
            lambda: Injector.get_instance(I),
            lambda: Injector.get_instance(Impl),
            lambda: Injector.get_instance(S),
            lambda: Injector.override(S)(T),
            lambda: Injector.implements(J)(JImpl),
        )

        impl = value(result_i)
        assert value(result_impl) is impl
        assert type(impl) is Impl
        assert built.count(Impl) == 1

        value(result_implements)

        s = value(result_s)
        if succeeded(result_override):
            assert type(s) is T, "override succeeded but S instance handed out"
            assert built.count(S) == 0 and built.count(T) == 1, f"constructed: {built}"
        else:
            assert isinstance(error(result_override), SingletonFrozenError)
            assert type(s) is S, "override was refused but T instance handed out"
            assert built.count(T) == 0 and built.count(S) == 1, f"constructed: {built}"

        assert provide(I) is impl
        assert provide(Impl) is impl
        assert provide(S) is s
        if succeeded(result_override):
            assert provide(T) is s
        assert type(provide(J)) is JImpl
        assert built.count(JImpl) == 1


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------

# C17
@bounded
def test_concurrent_component_registration_in_container(reset_injector):
    """N threads registering distinct components: all present exactly once and the container built once."""
    built = []

    @Injector.singleton
    class Registry(Container):
        def __init__(self):
            super().__init__()
            built.append(self)
            time.sleep(SLOW)

    def make_component(index):
        def component():
            return index

        component.__name__ = f"component_{index}"
        return component

    components = [make_component(index) for index in range(N)]
    results = run_concurrently(*[lambda c=c: Registry.component(c) for c in components])
    for component, result in zip(components, results):
        assert value(result) is component

    registry = provide(Registry)
    assert len(built) == 1, f"container constructed {len(built)} times"
    assert registry is built[0]
    registered = [registration.component for registration in registry.components]
    assert len(registered) == N
    assert set(registered) == set(components)
