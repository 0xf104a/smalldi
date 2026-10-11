import copy
import enum
from contextlib import AbstractContextManager
from typing import Callable

from smalldi.concurrency import threadsafe
from smalldi._singleton import LazySingleton
from smalldi._interfaces import InterfaceResolver


# Context maybe:
# 1) Same as Injector's one
# 2) Copy of Injector's one: achieved by copying each LazySingleton types, but not implementation instances
# 3) Empty: no singletons registered
class InjectionSubcontextType(enum.Enum):
    PRESERVE = enum.auto()
    RESET = enum.auto()
    EMPTY = enum.auto()
    SHALLOW = enum.auto()  # Shallow copy of singletons available; allows to modify current unfrozen+add new which are hidden from upper
    STACK = enum.auto()  # Current default implementations type becomes new default implementations, but current override types become new default impls too


class InjectionContext:  # Thread UNSAFE. Use via Injector
    # Case (1): same as Injector's one
    def __init__(self, inherited_singletons: dict[type, LazySingleton] | None = None,
                 interfaces: InterfaceResolver | None = None):
        if inherited_singletons is None:
            inherited_singletons = dict()
        if interfaces is None:
            interfaces = InterfaceResolver()
        self.singletons_available: dict[type, LazySingleton] = inherited_singletons
        self.interface_resolver: InterfaceResolver = interfaces

    def get_lazy_singleton(self, cls: type) -> LazySingleton:
        return self.singletons_available[cls]

    # Case (3)
    @classmethod
    def empty(cls) -> 'InjectionContext':
        return cls()

    # Case (2): new JIT creation, so singletons unfrozen
    def resetted(self) -> 'InjectionContext':
        new_singletons: dict[type, LazySingleton] = dict()
        clones_by_id: dict[int, LazySingleton] = dict()
        for key, singleton in self.singletons_available.items():
            cloned = clones_by_id.get(id(singleton))
            if cloned is None:
                cloned = singleton.clone()
                clones_by_id[id(singleton)] = cloned
            new_singletons[key] = cloned
        return self.__class__(new_singletons, self.interface_resolver.rewired(new_singletons))

    def stacked(self) -> 'InjectionContext':
        new_singletons: dict[type, LazySingleton] = dict()
        stacked_by_id: dict[int, LazySingleton] = dict()
        for key, singleton in self.singletons_available.items():
            stacked_singleton = stacked_by_id.get(id(singleton))
            if stacked_singleton is None:
                effective_cls = singleton.override_cls
                if effective_cls is None:
                    effective_cls = singleton.implementation_cls
                stacked_singleton = LazySingleton(effective_cls)
                stacked_by_id[id(singleton)] = stacked_singleton
            new_singletons[key] = stacked_singleton
        return self.__class__(new_singletons, self.interface_resolver.rewired(new_singletons).stacked())

    def shallow_copied(self) -> 'InjectionContext':
        shallowed_singletons = copy.copy(self.singletons_available)
        return self.__class__(shallowed_singletons,
                              self.interface_resolver.rewired(shallowed_singletons))


class InjectionContextManager(AbstractContextManager):
    def __init__(self, injector: 'Injector', context_factory: Callable[[], InjectionContext]):
        self.injector = injector
        self._context_factory = context_factory
        self._token: object | None = None

    def __enter__(self) -> InjectionContext:
        with self.injector.__class_mutex__:
            if self._token is not None:
                raise RuntimeError("Injection context manager was already entered")
            context = self._context_factory()
            self._token = self.injector._context_registry.push_context(context)
        return context

    def __exit__(self, _exc_type, _exc_value, _traceback, /):
        with self.injector.__class_mutex__:
            if self._token is None:
                raise RuntimeError("Injection context manager was exited without being entered")
            self.injector._context_registry.pop_context(self._token)

class ContextStackManager:
    def __init__(self, root_context: 'InjectionContext'):
        self.root_context = root_context
        self._context_per_id

    @threadsafe
    def context_stack_for_current_thread(self) -> list[InjectionContext]:
        pass
