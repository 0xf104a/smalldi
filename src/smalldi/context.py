"""
Injection contexts: the registries `Injector` reads and writes, and the subcontext kinds.

An `InjectionContext` holds one registry of singletons and one of interfaces.
`Injector` keeps a root context and, per execution slice, a stack of contexts
pushed with `with Injector.context(kind):`; every decorator and every instance
request goes to the context on top of the current slice's stack, or to the root
when nothing is pushed. `InjectionSubcontextType` names the five ways a child
context is derived from its parent.
"""
import copy
import enum
from contextlib import AbstractContextManager
from typing import Callable, TYPE_CHECKING

from smalldi._singleton import LazySingleton
from smalldi._interfaces import InterfaceResolver

if TYPE_CHECKING:
    from smalldi import Injector


class InjectionSubcontextType(enum.Enum):
    """
    How `Injector.context(kind)` derives the new context from the current one.

    The child is built at `__enter__` time from the context that is current
    then. Each member names what the child shares with its parent:

    * `PRESERVE`: the same `InjectionContext` object as the current one.
      Nothing is copied; registrations and instances made inside the block are
      made in the parent.
    * `RESET`: the same registrations, implementations and overrides, but
      every singleton is a fresh, unfrozen `LazySingleton` without an
      instance. Classes sharing one singleton through an override keep sharing
      one in the new context, and interfaces are rebound to the new
      singletons. The default kind.
    * `EMPTY`: nothing registered; no singleton and no interface.
    * `SHALLOW`: a new registry dict holding the *same* `LazySingleton`
      objects as the parent, so instances and frozen state are shared with
      the parent. Singletons registered inside are invisible to the parent.
      Overriding an inherited singleton inside the child mutates the shared
      object, so the override is visible in the parent as well.
    * `STACK`: each singleton's effective class, its override if it has one
      and its own class otherwise, becomes the base of a fresh singleton with
      no override, so it can be overridden again. Classes that shared one
      singleton keep sharing one. An interface's override becomes its
      implementation, so the interface can be overridden again as well.
    """
    PRESERVE = enum.auto()  # the current InjectionContext object itself
    RESET = enum.auto()  # same bindings, fresh unfrozen singletons without instances (default)
    EMPTY = enum.auto()  # nothing registered
    SHALLOW = enum.auto()  # new registry dict, same LazySingleton objects: instances and frozen state shared
    STACK = enum.auto()  # every effective class (override or own class) becomes a fresh base without override


# One InjectionContext may be shared between threads (PRESERVE, SHALLOW, ContextAwareThread);
# it is safe only because every access goes through Injector under its class mutex.
class InjectionContext:
    """
    One registry of singletons and one of interfaces, as read and written by `Injector`.

    `singletons_available` maps every registered class to its `LazySingleton`;
    an overridden class and its override map to one object. `interface_resolver`
    holds the interfaces and their bindings, which refer to those `LazySingleton`
    objects. The root context is created empty by `Injector`; child contexts
    are derived with `resetted()`, `stacked()`, `shallow_copied()` and
    `empty()`, one per `InjectionSubcontextType`. A context has no lock of its
    own: `Injector` accesses it under its class mutex only, which is what
    makes sharing one context between threads safe.

    :ivar singletons_available: registered singleton classes and their `LazySingleton` objects
    :ivar interface_resolver: the `InterfaceResolver` holding the registered interfaces
    """
    def __init__(self, inherited_singletons: dict[type, LazySingleton] | None = None,
                 interfaces: InterfaceResolver | None = None):
        """
        :param inherited_singletons: registry dict to use as is, or None for a new empty one
        :param interfaces: `InterfaceResolver` to use as is, or None for a new empty one
        """
        if inherited_singletons is None:
            inherited_singletons = dict()
        if interfaces is None:
            interfaces = InterfaceResolver()
        self.singletons_available: dict[type, LazySingleton] = inherited_singletons
        self.interface_resolver: InterfaceResolver = interfaces

    def get_lazy_singleton(self, cls: type) -> LazySingleton:
        """
        Returns the `LazySingleton` registered for a class.

        :param cls: registered singleton class
        :return: its `LazySingleton`, shared with the class it overrides or is overridden by
        :raises KeyError: if `cls` is not registered in this context
        """
        return self.singletons_available[cls]

    @classmethod
    def empty(cls) -> 'InjectionContext':
        """
        Creates a context with nothing registered: the `EMPTY` kind.

        :return: a new context with no singleton and no interface
        """
        return cls()

    def resetted(self) -> 'InjectionContext':
        """
        Derives the `RESET` child: same bindings, fresh unfrozen singletons.

        Every `LazySingleton` is cloned with its class, its override class and
        its override mark, but without its instance and without its frozen
        state. Keys that map to one `LazySingleton` here map to one clone, so
        an overridden class and its override still share an instance. The
        interfaces are rebound to the clones, with unfrozen bindings.

        :return: a new context whose instances are created independently of this one
        """
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
        """
        Derives the `STACK` child: every effective class becomes a new base.

        For each `LazySingleton`, its override class if it has one, else its
        own class, becomes the class of a fresh `LazySingleton` that has no
        override and no instance and is not frozen, so it accepts a new
        override. Keys that map to one `LazySingleton` here map to one new
        object. Each interface's override, or its implementation if it has no
        override, becomes the implementation of the new binding, which has no
        override and accepts one.

        :return: a new context in which every override of this one is the base
        """
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
        """
        Derives the `SHALLOW` child: a new registry dict with the same `LazySingleton` objects.

        Instances and frozen state are shared with this context. A singleton
        registered in the child is a new key in the child's dict only, so the
        parent never sees it. An override of an inherited singleton mutates
        the shared `LazySingleton`, so the parent resolves to the override as
        well. The interfaces get new, unfrozen bindings that refer to the
        shared `LazySingleton` objects.

        :return: a new context sharing every existing singleton with this one
        """
        shallowed_singletons = copy.copy(self.singletons_available)
        return self.__class__(shallowed_singletons,
                              self.interface_resolver.rewired(shallowed_singletons))


class InjectionContextManager(AbstractContextManager):
    """
    Single-use context manager returned by `Injector.context` and `Injector.foreign_context`.

    Creating the manager pushes nothing. `__enter__` builds the context by
    calling the factory, so a `RESET`, `STACK` or `SHALLOW` child is derived
    from the context that is current at that moment, and pushes it on the
    current execution slice. `__exit__` pops exactly the context this manager
    pushed. Both run under the injector's class mutex.

    :ivar injector: the `Injector` class whose registry is pushed to
    """
    def __init__(self, injector: 'Injector', context_factory: Callable[[], InjectionContext]):
        """
        :param injector: the `Injector` class
        :param context_factory: called once, at `__enter__`, to build the context to push
        """
        self.injector = injector
        self._context_factory = context_factory
        self._token: object | None = None

    def __enter__(self) -> InjectionContext:
        """
        Builds the context and pushes it on the current execution slice.

        :return: the pushed `InjectionContext`, which `Injector.get_context` returns inside the block
        :raises RuntimeError: if this manager was entered before, even if it was exited since
        """
        with self.injector.__class_mutex__:
            if self._token is not None:
                raise RuntimeError("Injection context manager was already entered")
            context = self._context_factory()
            self._token = self.injector._context_registry.push_context(context)
        return context

    def __exit__(self, _exc_type, _exc_value, _traceback, /):
        """
        Pops the context this manager pushed, making the enclosing context current again.

        Exceptions from the block propagate unchanged.

        :raises RuntimeError: if this manager was never entered, or the context it pushed is not
            the current slice's innermost context, in which case the stack is left unchanged
        """
        with self.injector.__class_mutex__:
            if self._token is None:
                raise RuntimeError("Injection context manager was exited without being entered")
            self.injector._context_registry.pop_context(self._token)
