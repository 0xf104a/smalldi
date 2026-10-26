"""
Injection contexts: the registries `Injector` reads and writes, and the subcontext kinds.

An `InjectionContext` holds one registry of singletons and one of interfaces.
`Injector` keeps a root context and, per execution slice, a stack of contexts
pushed with `with Injector.context(kind):`; every decorator and every instance
request goes to the context on top of the current slice's stack, or to the root
when nothing is pushed. `InjectionSubcontextType` names the five ways a child
context is derived from its parent. `InjectionContextSingletonOverride`
declares a `SHALLOW` child with singletons of its own as a dataclass.
"""
import copy
import dataclasses
import enum
import functools
import types
from contextlib import AbstractContextManager
from inspect import isabstract
from typing import (Annotated, Any, Callable, ClassVar, TYPE_CHECKING, Union, cast,
                    get_args, get_origin, get_type_hints)

from smalldi._singleton import LazySingleton
from smalldi._interfaces import InterfaceResolver
from smalldi.annotation import _Provide
from smalldi.decorator import oneshot, OneshotLevel

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
    def __init__(self, injector: 'type[Injector]', context_factory: Callable[[], InjectionContext]):
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


class _Field:
    """
    One declared field of an `InjectionContextSingletonOverride` subclass, read once per class.

    :ivar name: the field name
    :ivar tp: the declared class `T`
    :ivar default: zero-argument callable returning the class-level default: the field's default
        value, the result of its default factory, or None when it has neither
    """
    def __init__(self, name: str, tp: type, default: Callable[[], Any]):
        self.name = name
        self.tp = tp
        self.default = default


class _Declaration:
    """
    One field of an `InjectionContextSingletonOverride` with its value for one `Injector.context(...)` call.

    :ivar name: the field name, for error messages
    :ivar tp: the declared class
    :ivar instance: the value to preset, or None to preset nothing
    """
    def __init__(self, field: _Field, instance: Any):
        self.name = field.name
        self.tp = field.tp
        self.instance = instance

    @property
    def has_instance(self) -> bool:
        return self.instance is not None


class _DeclaredContext:
    """
    The declarations of one `Injector.context(...)` call, ready to derive the child context.

    Built when the context manager is created, so default factories run
    then; `derive` runs at `__enter__`, against the context current at that
    moment.
    """
    def __init__(self, declarations: list[_Declaration]):
        self.declarations = declarations

    def derive(self, parent: InjectionContext) -> InjectionContext:
        """
        Derives the `SHALLOW` child of `parent` with the declared singletons of its own.

        `parent` and its `LazySingleton` objects are only read: every object
        the child gets is new, so a failure leaves `parent` as it was.

        :param parent: the context to derive the child from
        :return: the child context, not pushed
        :raises TypeError: if two fields resolve to one singleton
        """
        singletons = copy.copy(parent.singletons_available)
        clones: dict[int, LazySingleton] = dict()
        claimed: dict[int, str] = dict()
        for d in self.declarations:
            target = parent.singletons_available.get(d.tp)
            if target is None:
                fresh = LazySingleton(d.tp)
                if d.has_instance:
                    fresh.set_instance(d.instance)
                singletons[d.tp] = fresh
                continue
            other = claimed.get(id(target))
            if other is not None:
                raise TypeError(f"Fields {other!r} and {d.name!r} resolve to one singleton; declare it once")
            claimed[id(target)] = d.name
            cloned = target.clone()
            if d.has_instance:
                cloned.set_instance(d.instance)
            clones[id(target)] = cloned
        for key, registered_singleton in list(singletons.items()):
            cloned = clones.get(id(registered_singleton))
            if cloned is not None:
                singletons[key] = cloned
        return InjectionContext(singletons, parent.interface_resolver.rewired(singletons))


class _hybridmethod:
    """
    Descriptor binding a function to the instance when accessed on one, and to the class otherwise.
    """
    def __init__(self, fn: Callable):
        self.__func__ = fn
        self.__doc__ = fn.__doc__
        self.__name__ = fn.__name__

    def __get__(self, obj: object, owner: type | None = None) -> types.MethodType:
        return types.MethodType(self.__func__, owner if obj is None else obj)


class InjectionContextSingletonOverride:
    """
    Base class whose fields declare a `SHALLOW` child context with singletons of its own.

    Subclass it, decorate the subclass with `@dataclasses.dataclass`, and
    declare one field per class the block needs::

        @dataclasses.dataclass
        class StormyVisits(InjectionContextSingletonOverride):
            jar: CookieJar                              # the block's own CookieJar, built on first use
            bowl: SnackBowl                             # not registered outside: injectable in the block only
            spot: NapSpot = NapSpot("the windowsill")   # the block's own NapSpot, with this instance

        with Injector.context(StormyVisits):                          # the class: its defaults
            ...
        with Injector.context(StormyVisits(spot=NapSpot("the box"))): # an instance: its values
            ...

    `apply(context)` on the class or an instance derives the same child from
    a given context and returns it unpushed. Every class not declared is shared
    with the parent: the child's registry dict is new, but it holds the
    parent's `LazySingleton` objects. Each declared `T` gets a singleton of
    its own in the child:

    * a registered `T` gets a clone of its singleton, made as the `RESET`
      kind makes it: same class and override class, no instance, not frozen.
      Instances created and overrides declared for `T` in the block stay in
      the block. Classes sharing that singleton with `T` share the clone;
    * an unregistered `T` is registered in the child only.

    `T` is a concrete class: an abstract class, registered as an interface
    or not, is refused as a field with `TypeError`. The implementation of an
    interface is preset through the concrete singleton class implementing
    it. The parent's interfaces stay bound in the child, to the clones where
    their singletons are declared.

    `n: T = instance` gives the child's singleton `instance` and freezes it;
    the parent never sees it. A value of None presets nothing, so None
    itself can't be preset, and `T | None = None` makes a field optional in
    the instance form. A value is injected as is, it isn't checked against
    `T`. The field types are read once per class; the values once per
    `Injector.context(...)` call, when a default factory runs too. The checks
    run at `__enter__`, against the context current then; the parent is
    never changed. `Provide[T]` has no meaning here and is rejected. A
    subclass without the dataclass decorator works through its annotations
    and class attributes, in the class form.
    """

    @_hybridmethod
    def apply(self_or_cls, context: InjectionContext) -> InjectionContext:
        """
        Derives the declared child of `context` without pushing anything.

        On the class, the fields' defaults are the values; on an instance,
        its attributes. `context` is only read, and the child is returned as
        `Injector.context(self_or_cls).__enter__()` would build it from the
        current context; `Injector.foreign_context(child)` pushes it.

        :param context: the context to derive the child from
        :return: the child context, not pushed
        :raises TypeError: if a field's annotation is `Provide[T]`, isn't a class or is an abstract
            class, two fields declare one class, or two fields resolve to one singleton
        """
        if isinstance(self_or_cls, type):
            declared = self_or_cls._from_class()
        else:
            declared = self_or_cls._from_instance()
        return declared.derive(context)

    @classmethod
    def _from_class(cls) -> _DeclaredContext:
        """
        The declarations of the class form: every field with its default.

        :return: the declarations, with default factories already run
        :raises TypeError: see `_fields`
        """
        return _DeclaredContext([_Declaration(field, field.default()) for field in cls._fields()])

    def _from_instance(self) -> _DeclaredContext:
        """
        The declarations of the instance form: every field with this instance's value.

        :return: the declarations
        :raises TypeError: see `_fields`
        """
        return _DeclaredContext([_Declaration(field, getattr(self, field.name)) for field in self._fields()])

    @oneshot(OneshotLevel.PER_CLASS)
    @classmethod
    def _fields(cls) -> tuple[_Field, ...]:
        """
        Reads the declared fields of the class, once per class.

        A dataclass contributes `dataclasses.fields`, so `ClassVar` and
        `InitVar` pseudo-fields are skipped and `default_factory` is
        honoured; any other class its annotations, with the class attribute
        of the same name as the default. Annotations are resolved with
        `typing.get_type_hints`, so string annotations work.

        :return: the fields, in declaration order
        :raises TypeError: if a field's annotation is `Provide[T]`, isn't a class or is an abstract
            class, or two fields declare one class
        """
        hints = get_type_hints(cls, include_extras=True)
        sources: list[tuple[str, Callable[[], Any]]] = []
        if "__dataclass_fields__" in cls.__dict__:
            for field in dataclasses.fields(cast(Any, cls)):
                if field.default_factory is not dataclasses.MISSING:
                    sources.append((field.name, field.default_factory))
                else:
                    default = None if field.default is dataclasses.MISSING else field.default
                    sources.append((field.name, functools.partial(_identity, default)))
        else:
            for name, hint in hints.items():
                if hint is ClassVar or get_origin(hint) is ClassVar:
                    continue
                sources.append((name, functools.partial(_identity, getattr(cls, name, None))))
        fields: list[_Field] = []
        seen: dict[type, str] = dict()
        for name, default in sources:
            tp = cls._unwrap(name, hints[name])
            if isabstract(tp):
                raise TypeError(f"Field {name!r}: {tp.__name__} is abstract; an InjectionContextSingletonOverride "
                                f"can't declare interfaces, declare the implementing singleton instead")
            if tp in seen:
                raise TypeError(f"Fields {seen[tp]!r} and {name!r} both declare {tp.__name__}")
            seen[tp] = name
            fields.append(_Field(name, tp, default))
        return tuple(fields)

    @staticmethod
    def _unwrap(name: str, hint: Any) -> type:
        """
        Extracts the declared class from a field annotation.

        `T | None` and `Optional[T]` declare `T`; metadata of `Annotated[T, ...]` is dropped.

        :param name: the field name, for error messages
        :param hint: the resolved annotation
        :return: the declared class
        :raises TypeError: if `hint` is `Provide[T]`, or doesn't declare exactly one class
        """
        if get_origin(hint) in (Union, types.UnionType):
            members = [m for m in get_args(hint) if m is not type(None)]
            if len(members) == 1:
                hint = members[0]
        if get_origin(hint) is Annotated:
            inner, *meta = get_args(hint)
            if any(m is _Provide for m in meta):
                raise TypeError(f"Field {name!r}: Provide[T] has no meaning in a context override; "
                                f"declare the singleton as T")
            hint = inner
        if not isinstance(hint, type) or get_origin(hint) is not None:
            raise TypeError(f"Field {name!r}: {hint!r} is not a class; declare a singleton as T")
        return hint


def _identity(value: Any) -> Any:
    return value
