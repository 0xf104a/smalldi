import threading
from abc import ABC

import pytest

from smalldi._singleton import LazySingleton, SingletonFrozenError


class Base:
    pass


class Child(Base):
    pass


class GrandChild(Child):
    pass


class OtherChild(Base):
    pass


class Unrelated:
    pass


# --- instances


def test_instance_is_created_lazily_and_once():
    created = []

    class Service:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Service)
    assert created == []
    assert not singleton.frozen

    instance = singleton.get_instance()
    assert singleton.get_instance() is instance
    assert created == [instance]
    assert singleton.frozen


def test_factory_replaces_class_construction():
    calls = []

    def factory():
        calls.append(1)
        return "built"

    singleton = LazySingleton(Base, factory=factory)
    assert singleton.get_instance() == "built"
    assert singleton.get_instance() == "built"
    assert calls == [1]
    assert singleton.cls is Base


def test_factory_is_skipped_when_overridden():
    singleton = LazySingleton(Base, factory=lambda: pytest.fail("factory must not run"))
    child = LazySingleton(Child)
    singleton.override(child)
    assert singleton.get_instance() is child.get_instance()


def test_failed_construction_still_freezes():
    class Broken:
        def __init__(self):
            raise RuntimeError("boom")

    singleton = LazySingleton(Broken)
    with pytest.raises(RuntimeError):
        singleton.get_instance()
    assert singleton.frozen
    with pytest.raises(SingletonFrozenError):
        singleton.override(LazySingleton(type("Fixed", (Broken,), {"__init__": lambda self: None})))


def test_concurrent_get_instance_creates_one_instance():
    threads_count = 8
    barrier = threading.Barrier(threads_count)
    created = []

    class Slow:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Slow)
    results = []

    def worker():
        barrier.wait()
        results.append(singleton.get_instance())

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(1)

    assert len(created) == 1
    assert len(results) == threads_count
    assert all(r is created[0] for r in results)


def test_constructor_may_resolve_other_singleton_while_override_is_declared():
    """Creating an instance doesn't hold the bindings lock, so it can't deadlock with override()"""
    other = LazySingleton(Base)
    entered = threading.Event()
    release = threading.Event()

    class Slow:
        def __init__(self):
            entered.set()
            release.wait(1)
            self.dependency = other.get_instance()

    slow = LazySingleton(Slow)
    worker = threading.Thread(target=slow.get_instance)
    worker.start()
    assert entered.wait(1)

    # Rebinding another singleton while Slow is being constructed doesn't block
    other.override(LazySingleton(Child))
    release.set()
    worker.join(1)
    assert not worker.is_alive()
    assert type(slow.get_instance().dependency) is Child


# --- overrides


def test_override_shares_the_override_instance():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)

    assert base.override_singleton is child
    assert base.get_instance() is child.get_instance()
    assert type(base.get_instance()) is Child


def test_overridden_class_is_never_instantiated():
    created = []

    class Service:
        def __init__(self):
            created.append(type(self))

    class Fake(Service):
        pass

    service = LazySingleton(Service)
    service.override(LazySingleton(Fake))
    service.get_instance()
    assert created == [Fake]


def test_get_instance_freezes_the_whole_chain():
    base, child = LazySingleton(Base), LazySingleton(Child)
    base.override(child)
    base.get_instance()
    assert base.frozen
    assert child.frozen


def test_overrides_are_transitive():
    base, child, grandchild = LazySingleton(Base), LazySingleton(Child), LazySingleton(GrandChild)
    base.override(child)
    child.override(grandchild)

    assert base.get_instance() is grandchild.get_instance()
    assert child.get_instance() is grandchild.get_instance()


def test_override_must_be_subclass():
    with pytest.raises(TypeError, match="not a subclass"):
        LazySingleton(Base).override(LazySingleton(Unrelated))


def test_override_with_itself_is_rejected():
    base = LazySingleton(Base)
    with pytest.raises(TypeError, match="itself"):
        base.override(base)
    with pytest.raises(TypeError, match="itself"):
        base.override(LazySingleton(Base))


def test_second_override_is_rejected():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)
    with pytest.raises(TypeError, match="already overridden"):
        base.override(LazySingleton(OtherChild))
    assert base.override_singleton is child


def test_repeating_current_override_is_noop():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)
    base.override(child)
    assert base.override_singleton is child


def test_override_with_another_singleton_of_same_class_is_rejected():
    """Only identity counts: a second wrapper of the same class is another override"""
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)
    with pytest.raises(TypeError, match="already overridden"):
        base.override(LazySingleton(Child))
    assert base.override_singleton is child


def test_override_after_get_instance_is_rejected():
    base = LazySingleton(Base)
    base.get_instance()
    with pytest.raises(SingletonFrozenError):
        base.override(LazySingleton(Child))


def test_repeating_current_override_is_allowed_after_freeze():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)
    base.get_instance()
    base.override(child)
    assert base.override_singleton is child


def test_frozen_override_cannot_be_rebound_even_to_same_class():
    base = LazySingleton(Base)
    base.override(LazySingleton(Child))
    base.get_instance()
    with pytest.raises(SingletonFrozenError):
        base.override(LazySingleton(Child))


def test_check_override_changes_nothing():
    base = LazySingleton(Base)
    base.check_override(LazySingleton(Child))
    assert base.override_singleton is None
    with pytest.raises(TypeError):
        base.check_override(LazySingleton(Unrelated))


def test_override_cycle_is_rejected():
    class Anything(ABC):
        @classmethod
        def __subclasshook__(cls, subclass):
            return True

    # __subclasshook__ makes the classes subclasses of each other
    class A(Anything):
        pass

    class B(Anything):
        pass

    assert issubclass(A, B) and issubclass(B, A)
    a, b = LazySingleton(A), LazySingleton(B)
    a.override(b)
    with pytest.raises(TypeError, match="cycle"):
        b.override(a)
