import threading

import pytest

from smalldi._singleton import LazySingleton, SingletonFrozenError


class Base:
    pass


class Child(Base):
    pass


class Unrelated:
    pass


def test_instance_is_created_lazily_and_once():
    created = []

    class Service:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Service, None)
    assert created == []
    assert not singleton.frozen

    instance = singleton.get_instance()
    assert singleton.get_instance() is instance
    assert created == [instance]
    assert singleton.frozen


def test_constructor_override():
    singleton = LazySingleton(Base, Child)
    assert type(singleton.get_instance()) is Child


def test_constructor_override_must_be_subclass():
    with pytest.raises(TypeError):
        LazySingleton(Base, Unrelated)


def test_override_before_instantiation():
    singleton = LazySingleton(Base, None)
    singleton.override(Child)
    assert type(singleton.get_instance()) is Child


def test_override_with_same_class_is_noop():
    singleton = LazySingleton(Base, None)
    singleton.override(Base)
    singleton.override(Base)
    assert type(singleton.get_instance()) is Base


def test_override_twice_is_rejected():
    class OtherChild(Base):
        pass

    singleton = LazySingleton(Base, None)
    singleton.override(Child)
    singleton.override(Child)
    with pytest.raises(TypeError):
        singleton.override(OtherChild)


def test_override_must_be_subclass():
    singleton = LazySingleton(Base, None)
    with pytest.raises(TypeError):
        singleton.override(Unrelated)


def test_override_after_instantiation_is_rejected():
    singleton = LazySingleton(Base, None)
    singleton.get_instance()
    with pytest.raises(SingletonFrozenError):
        singleton.override(Child)


def test_concurrent_get_instance_creates_one_instance():
    threads_count = 8
    barrier = threading.Barrier(threads_count)
    created = []

    class Slow:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Slow, None)
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
