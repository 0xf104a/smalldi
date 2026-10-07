"""
Containers: singletons that collect classes and functions registered with a decorator.
"""
import dataclasses
from inspect import isfunction, isclass
from typing import Any, Iterable

from smalldi import Injector


@dataclasses.dataclass
class ComponentRegistration:
    """
    Registration of a component in a container.

    :param component: the registered class or function
    :param args: positional metadata passed to the component decorator
    :param kwargs: keyword metadata passed to the component decorator
    """
    component: Any
    args: tuple[Any]
    kwargs: dict[str, Any]

class Container:
    """
    Base class of containers, singletons that collect classes and functions.

    Subclass it, register the subclass with `@Injector.singleton`, and
    decorate classes or functions with `@MyContainer.component` or
    `@MyContainer.component(*args, **kwargs)`. Each registration is appended
    to the container instance's `components` list and reported to
    `_on_component_register`. The first registration instantiates the
    container through `Injector.get_instance`, which freezes it: a container
    may only be overridden before any component is registered. If it is
    overridden, the override's instance receives the components.

    :ivar components: registrations in registration order
    """
    def __init__(self):
        self.components: list[ComponentRegistration] = []

    def _get_components(self) -> Iterable[Any]:
        """
        Yields the registered components, without their metadata, in registration order.

        :return: iterator of the registered classes and functions
        """
        for registration in self.components:
            yield registration.component

    def _on_component_register(self, registration: ComponentRegistration):
        """
        Hook called after each registration; does nothing by default.

        :param registration: the registration just appended to `components`
        :return: None
        """
        pass

    @classmethod
    def _register_component(cls, component: Any, args: tuple[Any], kwargs: dict[str, Any]):
        """
        Appends a registration to the container instance and calls `_on_component_register`.

        The instance is obtained from `Injector.get_instance(cls)`, which
        creates it on the first registration and freezes the container
        singleton. If the container is overridden, the override's instance is
        used.

        :param component: component to register
        :param args: positional metadata passed to the component decorator
        :param kwargs: keyword metadata passed to the component decorator
        :raises TypeError: if `cls` isn't a registered singleton, or `component` is None
        :raises RuntimeError: from `Injector.get_instance`, on a circular dependency
        :raises Exception: any exception raised by the container's constructor propagates unchanged
        """
        if not Injector.is_singleton(cls):
            raise TypeError(f"Injector must be a singleton to use components")
        if component is None:
            raise TypeError("Component cannot be None")
        this = Injector.get_instance(cls)
        this.components.append(ComponentRegistration(component, args, kwargs))
        this._on_component_register(ComponentRegistration(component, args, kwargs))

    @classmethod
    def component(cls, *args, **kwargs):
        """
        Registers a component in the container, as a plain decorator or as a decorator factory with metadata.

        Used as `@MyContainer.component`, i.e. called with exactly one
        positional argument that is a function or a class and no keyword
        arguments, it registers that argument without metadata and returns
        it. With any other arguments, it returns a decorator that registers
        the decorated object with `args` and `kwargs` as metadata and returns
        it unchanged. A single callable meant as metadata is therefore taken
        as the component.

        :param args: metadata arguments, or the component itself
        :param kwargs: metadata keyword arguments
        :return: the component, or a decorator registering it
        :raises TypeError: if the container isn't a registered singleton, or the component is None
        """
        if len(args) == 1 and len(kwargs) == 0\
            and (isfunction(args[0]) or isclass(args[0])):
            # No arguments were passed we are in no-call decorator case
            component = args[0]
            cls._register_component(component, tuple(), dict())
            return component

        def _wrapper(component):
            cls._register_component(component, args, kwargs)
            return component
        return _wrapper
