import enum
from contextlib import AbstractContextManager

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
    @classmethod
    def resetted(cls, inherited_singletons: dict[type, LazySingleton],
                 interface_resolver: InterfaceResolver) -> 'InjectionContext':
        new_singletons = dict()
        for key in inherited_singletons:
            singleton = inherited_singletons[key]
            new_singletons[key] = LazySingleton(singleton.implementation_cls, singleton.override_cls)
        return cls(new_singletons, interface_resolver.rewired(new_singletons))

    @classmethod
    def from_lazy_types_stacked(cls, inherited_singletons: dict[type, LazySingleton],
                                interface_resolver: InterfaceResolver) -> 'InjectionContext':
        new_singletons = dict()
        for key in inherited_singletons:
            singleton = inherited_singletons[key]
            new_impl = None
            if singleton.override_cls is not None:
                new_impl = singleton.override_cls
            else:
                new_impl = singleton.implementation_cls
            new_singletons[key] = LazySingleton(new_impl)
        return cls(new_singletons, interface_resolver.rewired(new_singletons).stacked())


class InjectionContextManager(AbstractContextManager):
    def __init__(self, injector: 'Injector'):
        self.injector = injector

    def __exit__(self, _exc_type, _exc_value, _traceback, /):
        self.injector.finalize_context()
