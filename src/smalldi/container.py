import dataclasses
from inspect import isfunction, isclass
from threading import RLock
from typing import Any, Iterable

from smalldi import Injector

@dataclasses.dataclass
class ComponentRegistration:
    """
    Registration of a component
    :param component: component itself
    :param args: arguments passed to the component decorator
    :param kwargs: keyword arguments passed to the component decorator
    """
    component: Any
    args: tuple[Any]
    kwargs: dict[str, Any]

# Registrations are kept per container class, so components may be registered before the container
# singleton is created; an instance gets components of every container class it inherits.
# _lock guards only these lists and is never held while calling user code (_on_component_register),
# so it is always acquired last: after the singleton creation lock, never before it.
_lock = RLock()
_registrations: list[tuple[type, ComponentRegistration]] = []
_instances: list["Container"] = []


class Container:
    """
    Container is a class that allows collecting classes or functions
    The container must be a singleton
    """
    @property
    def components(self) -> list[ComponentRegistration]:
        """
        Registrations of components of this container (and of the containers it inherits) in order
        of registration
        """
        with _lock:
            return [registration for owner, registration in _registrations if isinstance(self, owner)]

    def _on_singleton_created(self):
        # Called by the injector once the instance is fully created; replay registrations made before.
        # Adding the instance and taking the snapshot atomically hooks every registration exactly once
        with _lock:
            _instances.append(self)
            registrations = self.components
        for registration in registrations:
            self._on_component_register(registration)

    def _get_components(self) -> Iterable[Any]:
        """
        Function used by class itself to get components as an iterable
        :return: iterable of components
        """
        for registration in self.components:
            yield registration.component

    def _on_component_register(self, registration: ComponentRegistration):
        """
        Called when a component is registered, or, for components registered before
        the container was created, right after the container is created

        :param registration: registration data of a component
        :return: None
        """
        pass

    @classmethod
    def _register_component(cls, component: Any, args: tuple[Any], kwargs: dict[str, Any]):
        if cls not in Injector._singletons_available:
            raise TypeError(f"Injector must be a singleton to use components")
        if component is None:
            raise TypeError("Component cannot be None")
        registration = ComponentRegistration(component, args, kwargs)
        with _lock:
            _registrations.append((cls, registration))
            instances = [instance for instance in _instances if isinstance(instance, cls)]
        for instance in instances:
            instance._on_component_register(registration)

    @classmethod
    def component(cls, *args, **kwargs):
        """
        Registers a component in the container
        :param args: metadata arguments
        :param kwargs: metadata keyword arguments
        :return: wrapper function which registers a component and returns it unaltered
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
