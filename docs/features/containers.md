# Containers

A container is a singleton subclassing `smalldi.container.Container` that collects the classes and functions
decorated with `@MyContainer.component`, with optional metadata, so one place can iterate over everything that
registered itself.

## Example

```python
from smalldi import Injector, Provide
from smalldi.container import Container


@Injector.singleton
class SnackMenu(Container):
    def _on_component_register(self, registration):
        name = registration.kwargs.get("name", registration.component.__name__)
        print(f"on the menu: {name}")

    def serve(self):
        return [recipe() for recipe in self._get_components()]


@SnackMenu.component
def cookie():
    return "cookie"


@SnackMenu.component(name="tuna surprise")
def tuna():
    return "tuna"


@Injector.inject
def snack_time(menu: Provide[SnackMenu]):
    print(f"Pusheen tries {menu.serve()}")


snack_time()  # on the menu: cookie, on the menu: tuna surprise, Pusheen tries ['cookie', 'tuna']
print([registration.kwargs for registration in Injector.get_instance(SnackMenu).components])  # [{}, {'name': 'tuna surprise'}]
```

## What to know

* Register the subclass with `@Injector.singleton` first; `@MyContainer.component` on a class or function appends a
  `ComponentRegistration` to the container instance's `components` list. `@MyContainer.component(*args, **kwargs)`
  stores the arguments as metadata.
* `_get_components()` yields the components in registration order; `components` holds the registrations with their
  metadata. `_on_component_register(registration)` is called after each registration; the default does nothing.
* The first registration instantiates the container, which freezes it: a container can be
  [overridden](interfaces.md) only before any component is registered. Components registered after an override go
  to the overriding container's instance.
* Components register when their module is imported. `Collector.collect_from_package` imports every module of a
  package, so a plugin nobody imports still ends up in the container.

## Read on

* [README: Containers](../../README.md#containers), the full rules and `ComponentRegistration`
* [Use case: plugins and registries](../use-cases/plugins.md), a container filled by `Collector` across a package
