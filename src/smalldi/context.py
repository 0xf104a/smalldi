"""
Injection contexts: the registries `Injector` reads and writes, and the subcontext kinds.

An `InjectionContext` holds one registry of singletons and one of interfaces.
`Injector` keeps a root context and, per execution slice, a stack of contexts
pushed with `with Injector.context(kind):`; every decorator and every instance
request goes to the context on top of the current slice's stack, or to the root
when nothing is pushed. `InjectionSubcontextType` names the five ways a child
context is derived from its parent. `InjectionContextOverride` declares a
`SHALLOW` child with singletons and interface bindings of its own as a
dataclass; `InjectionContextSingletonOverride` is its deprecated alias.
"""
import copy
import dataclasses
import enum
import functools
import types
import warnings
from contextlib import AbstractContextManager
from inspect import isabstract
from typing import (Annotated, Any, Callable, ClassVar, TYPE_CHECKING, Union, cast,
                    get_args, get_origin, get_type_hints)

from smalldi._singleton import LazySingleton
from smalldi._interfaces import InterfaceResolver
from smalldi.annotation import _Provide, _ImplementationOf
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
    One declared field of an `InjectionContextOverride` subclass, read once per class.

    :ivar name: the field name
    :ivar tp: the declared class: a concrete singleton class, or the interface of an `ImplementationOf[I]` field
    :ivar default: zero-argument callable returning the class-level default: the field's default
        value, the result of its default factory, or None when it has neither
    :ivar is_interface: whether the field is `ImplementationOf[I]`, declaring the child's own binding for
        the interface `tp`
    """
    def __init__(self, name: str, tp: type, default: Callable[[], Any], is_interface: bool):
        self.name = name
        self.tp = tp
        self.default = default
        self.is_interface = is_interface


class _Declaration:
    """
    One field of an `InjectionContextOverride` with its value for one `Injector.context(...)` call.

    :ivar name: the field name, for error messages
    :ivar tp: the declared class: a concrete singleton class or, when `is_interface`, the interface
    :ivar instance: the value to preset, or None to preset nothing; for an interface, the instance `I` resolves to
    :ivar is_interface: whether the field is `ImplementationOf[I]`
    """
    def __init__(self, field: _Field, instance: Any):
        self.name = field.name
        self.tp = field.tp
        self.instance = instance
        self.is_interface = field.is_interface

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
        Derives the `SHALLOW` child of `parent` with the declared singletons and interface bindings of its own.

        `parent`, its `LazySingleton` objects and its resolver are only read:
        every object the child gets is new and private until the context is
        pushed, so a failure leaves `parent` as it was. Every check that can
        fail runs in the first loop; `rewired` and `redeclare` run after the
        last check, on the new resolver only. An `ImplementationOf[I]` field
        with a value registers the child's own singleton for `type(value)`
        exactly as a concrete field would, then `redeclare` binds it as the
        frozen implementation of `I`; without a value `redeclare` gives `I` an
        unbound binding.

        :param parent: the context to derive the child from
        :return: the child context, not pushed
        :raises TypeError: if two fields resolve to one singleton, including a preset whose class another
            field declares
        """
        singletons = copy.copy(parent.singletons_available)
        clones: dict[int, LazySingleton] = dict()
        claimed: dict[int, str] = dict()
        fresh: dict[type, str] = dict()
        interfaces: list[tuple[type, LazySingleton | None]] = []

        def own(name: str, cls: type, instance: Any) -> LazySingleton:
            """The child's own singleton for `cls`: a clone of the parent's or a new registration, with `instance` if any."""
            target = parent.singletons_available.get(cls)
            if target is None:
                other = fresh.get(cls)
                if other is not None:
                    raise TypeError(f"Fields {other!r} and {name!r} resolve to one singleton; declare it once")
                created = LazySingleton(cls)
                if instance is not None:
                    created.set_instance(instance)
                fresh[cls] = name
                singletons[cls] = created
                return created
            other = claimed.get(id(target))
            if other is not None:
                raise TypeError(f"Fields {other!r} and {name!r} resolve to one singleton; declare it once")
            claimed[id(target)] = name
            cloned = target.clone()
            if instance is not None:
                cloned.set_instance(instance)
            clones[id(target)] = cloned
            return cloned

        for d in self.declarations:
            if d.is_interface:
                implementation = own(d.name, type(d.instance), d.instance) if d.has_instance else None
                interfaces.append((d.tp, implementation))
            else:
                own(d.name, d.tp, d.instance)
        for key, registered_singleton in list(singletons.items()):
            cloned = clones.get(id(registered_singleton))
            if cloned is not None:
                singletons[key] = cloned
        resolver = parent.interface_resolver.rewired(singletons)
        for interface, implementation in interfaces:
            resolver.redeclare(interface, implementation)
        return InjectionContext(singletons, resolver)


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


class InjectionContextOverride:
    """
    Base class whose fields declare a `SHALLOW` child context, a declared context, with singletons and interface
    bindings of its own.

    Subclass it, decorate the subclass with `@dataclasses.dataclass`, and
    declare one field per class or interface the block needs::

        @dataclasses.dataclass
        class StormyVisits(InjectionContextOverride):
            jar: CookieJar                              # the block's own CookieJar, built on first use
            bowl: SnackBowl                             # not registered outside: injectable in the block only
            spot: NapSpot = NapSpot("the windowsill")   # the block's own NapSpot, with this instance
            treat: ImplementationOf[Treat] | None = None  # the block's own binding of the interface Treat

        with Injector.context(StormyVisits):                          # the class: its defaults
            ...
        with Injector.context(StormyVisits(spot=NapSpot("the box"))): # an instance: its values
            ...
        with Injector.context(StormyVisits(treat=Tuna())):            # Treat resolves to this object in the block
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

    `T` is a concrete class. A field `n: ImplementationOf[I]`, `I` an
    abstract class, gives the child a binding of its own for the interface
    `I`:

    * without a value it has neither implementation nor override, whatever
      the parent has, so the block binds it with `@Injector.implements(I)` or
      `@Injector.override(I)`, on a singleton registered in the block or
      declared as a field; overriding with an inherited, undeclared
      singleton marks that shared object, and a request through the binding
      freezes it, as in any `SHALLOW` child. A request
      for `I` before it is bound raises `RuntimeError` and freezes the
      binding. An `I` the parent doesn't know is registered in the child only;
    * `n: ImplementationOf[I] = instance` registers the child's own singleton
      for `type(instance)` as a concrete field would, then binds it as the
      implementation of `I` and freezes the binding, so `Provide[I]` and
      `Provide[type(instance)]` are one object in the block; `instance` is
      not checked against `I`.

    The parent's binding for `I` is never changed. Every other interface of
    the parent stays bound in the child, to the clones where their singletons
    are declared. A plain abstract class is refused as a field with
    `TypeError`, as is `ImplementationOf[C]` with a concrete `C`.

    `n: T = instance` gives the child's singleton `instance` and freezes it;
    the parent never sees it. A value of None presets nothing, so None
    itself can't be preset, and `T | None = None` makes a field optional in
    the instance form. A value is injected as is, it isn't checked against
    `T`. The field types are read once per class; the values once per
    `Injector.context(...)` call, when a default factory runs too. The checks
    run at `__enter__`, against the context current then; the parent is
    never changed. `Provide[T]` has no meaning here and is rejected.

    A default that is a plain value other than None is one object, preset in
    every context derived from the class: the class form uses it, and so does
    every instance built without that argument. That warns with
    `UserWarning` once per class, on first use, and the value is used as it
    is; `dataclasses.field(default_factory=...)` makes a new one per context.

    A subclass with no dataclass among its bases works through its
    annotations and class attributes, in the class form. A subclass of a
    decorated subclass must be decorated with `@dataclasses.dataclass`
    itself, else `TypeError`: without the decorator its inherited fields
    would read as plain class attributes.
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
        :raises TypeError: if the class inherits dataclass fields without being decorated with
            `@dataclasses.dataclass` itself, a field's annotation is `Provide[T]`, isn't a class, is an
            abstract class without `ImplementationOf`, is `ImplementationOf[C]` with a concrete `C`, two
            fields declare one class, or two fields resolve to one singleton
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

        A default that is a plain value other than None is one object, preset
        in every context derived from the class; it warns with `UserWarning`,
        once per class, and is used as it is.

        :return: the fields, in declaration order
        :raises TypeError: if the class inherits dataclass fields without being decorated with
            `@dataclasses.dataclass` itself, a field's annotation is `Provide[T]`, isn't a class, is an
            abstract class without `ImplementationOf`, is `ImplementationOf[C]` with a concrete `C`, or
            two fields declare one class
        """
        if dataclasses.is_dataclass(cls) and "__dataclass_fields__" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} inherits dataclass fields but isn't decorated with @dataclasses.dataclass; "
                            f"decorate it")
        hints = get_type_hints(cls, include_extras=True)
        sources: list[tuple[str, Callable[[], Any]]] = []
        shared: list[str] = []
        if "__dataclass_fields__" in cls.__dict__:
            for field in dataclasses.fields(cast(Any, cls)):
                if field.default_factory is not dataclasses.MISSING:
                    sources.append((field.name, field.default_factory))
                else:
                    default = None if field.default is dataclasses.MISSING else field.default
                    if default is not None:
                        shared.append(field.name)
                    sources.append((field.name, functools.partial(_identity, default)))
        else:
            for name, hint in hints.items():
                if hint is ClassVar or get_origin(hint) is ClassVar:
                    continue
                default = getattr(cls, name, None)
                if default is not None:
                    shared.append(name)
                sources.append((name, functools.partial(_identity, default)))
        fields: list[_Field] = []
        seen: dict[type, str] = dict()
        for name, default in sources:
            tp, is_interface = cls._unwrap(name, hints[name])
            if is_interface and not isabstract(tp):
                raise TypeError(f"Field {name!r}: ImplementationOf[{tp.__name__}] needs an abstract class and "
                                f"{tp.__name__} is concrete; declare the singleton as {name}: {tp.__name__}")
            if not is_interface and isabstract(tp):
                raise TypeError(f"Field {name!r}: {tp.__name__} is abstract; declare the interface as "
                                f"{name}: ImplementationOf[{tp.__name__}], or declare the singleton class "
                                f"implementing it")
            if tp in seen:
                raise TypeError(f"Fields {seen[tp]!r} and {name!r} both declare {tp.__name__}")
            seen[tp] = name
            fields.append(_Field(name, tp, default, is_interface))
        for name in shared:
            warnings.warn(f"Field {name!r} of {cls.__name__}: the default is one object shared by every context; "
                          f"use dataclasses.field(default_factory=...) for a new one per context",
                          UserWarning, stacklevel=2)
        return tuple(fields)

    @staticmethod
    def _unwrap(name: str, hint: Any) -> tuple[type, bool]:
        """
        Extracts the declared class from a field annotation and tells whether it is an `ImplementationOf[I]` field.

        `T | None` and `Optional[T]` declare `T`; `Annotated[T, ...]` declares
        `T` and its metadata is read for the `ImplementationOf` marker, so
        `ImplementationOf[I] | None`, `Optional[ImplementationOf[I]]` and
        `ImplementationOf[I | None]` all declare `I` as an interface.

        :param name: the field name, for error messages
        :param hint: the resolved annotation
        :return: the declared class, and whether it was wrapped in `ImplementationOf`
        :raises TypeError: if `hint` contains `Provide[T]`, or doesn't declare exactly one class
        """
        is_interface = False
        while True:
            if get_origin(hint) in (Union, types.UnionType):
                members = [m for m in get_args(hint) if m is not type(None)]
                if len(members) != 1:
                    break
                hint = members[0]
            elif get_origin(hint) is Annotated:
                inner, *meta = get_args(hint)
                if any(m is _Provide for m in meta):
                    raise TypeError(f"Field {name!r}: Provide[T] has no meaning in a declared context; "
                                    f"declare the singleton as T")
                if any(m is _ImplementationOf for m in meta):
                    is_interface = True
                hint = inner
            else:
                break
        if not isinstance(hint, type) or get_origin(hint) is not None:
            raise TypeError(f"Field {name!r}: {hint!r} is not a class; declare a singleton as T")
        return hint, is_interface


def _identity(value: Any) -> Any:
    return value


def __getattr__(name: str) -> Any:
    """
    Serves the deprecated name `InjectionContextSingletonOverride` with a `DeprecationWarning`.

    The name is not cached in the module, so every import or attribute access
    warns.

    :param name: the attribute looked up on the module
    :return: `InjectionContextOverride` for the deprecated name
    :raises AttributeError: for any other name
    """
    if name == "InjectionContextSingletonOverride":
        warnings.warn("smalldi.context.InjectionContextSingletonOverride is deprecated and will be removed in 1.0.0; "
                      "use smalldi.context.InjectionContextOverride instead", DeprecationWarning, stacklevel=2)
        return InjectionContextOverride
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    InjectionContextSingletonOverride = InjectionContextOverride
