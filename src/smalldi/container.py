import dataclasses
from inspect import isfunction, isclass
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

class Container:
    """
    Container is a class that allows collecting classes or functions
    The container must be a singleton
    """
    def __init__(self):
        self.components: list[ComponentRegistration] = []

    def _get_components(self) -> Iterable[Any]:
        """
        Function used by class itself to get components as an iterable
        :return: iterable of components
        """
        for registration in self.components:
            yield registration.component

    def _on_component_register(self, registration: ComponentRegistration):
        """
        Called when a component is registered

        :param registration: registration data of a component
        :return: None
        """
        pass

    @classmethod
    def _register_component(cls, component: Any, args: tuple[Any], kwargs: dict[str, Any]):
        if cls not in Injector.singletons_available:
            raise TypeError(f"Injector must be a singleton to use components")
        if component is None:
            raise TypeError("Component cannot be None")
        this = Injector.singletons_available[cls]
        this.components.append(ComponentRegistration(component, args, kwargs))
        this._on_component_register(ComponentRegistration(component, args, kwargs))

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
