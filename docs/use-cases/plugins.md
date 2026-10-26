# Plugins and registries

A container collects the classes and functions decorated as its components; `Collector.collect_from_package` imports
every module of a package so that each plugin registers itself. The program then iterates over the container instead
of maintaining a list of plugins by hand.

## Example

The package below is written to a temporary directory so the example runs as-is; in a project it is part of the
source tree. Each plugin module registers a function in the `SnackMenu` container defined in `treats.menu`.

```python
import sys
import tempfile
import textwrap
from pathlib import Path

from smalldi import Injector, Provide
from smalldi.collector import Collector

PACKAGE = {
    "__init__.py": "",
    "menu.py": '''
        from smalldi import Injector
        from smalldi.container import Container

        @Injector.singleton
        class SnackMenu(Container):
            def serve(self):
                return [snack() for snack in self._get_components()]
    ''',
    "cookies.py": '''
        from treats.menu import SnackMenu

        @SnackMenu.component
        def cookie():
            return "cookie"
    ''',
    "fish.py": '''
        from treats.menu import SnackMenu

        @SnackMenu.component
        def tuna():
            return "tuna"
    ''',
}
root = Path(tempfile.mkdtemp())
(root / "treats").mkdir()
for name, source in PACKAGE.items():
    (root / "treats" / name).write_text(textwrap.dedent(source), encoding="utf-8")
sys.path.insert(0, str(root))

Collector.collect_from_package("treats")  # imports treats.cookies, treats.fish and treats.menu

from treats.menu import SnackMenu  # noqa: E402


@Injector.inject
def snack_time(menu: Provide[SnackMenu]):
    print(f"Pusheen's menu: {menu.serve()}")


snack_time()  # Pusheen's menu: ['cookie', 'tuna']
```

## How it fits together

**The container is a singleton.** `SnackMenu` subclasses `Container` and is registered with `@Injector.singleton`,
so anything can take `Provide[SnackMenu]`. The first `@SnackMenu.component` instantiates it.

**Plugins register themselves.** A plugin module imports the container and decorates its contribution. Nothing in the
program names the plugin; adding one is adding a module.

**The collector makes sure every module is imported.** Without it, `treats.fish` would register nothing until
somebody imported it. `collect_from_package` imports the package and every module and subpackage under it, in
`pkgutil.walk_packages` order, which is alphabetical within a directory. Call it once, at startup, from a top-level
module such as the entry point, before anything is injected. Calling it from a module that the plugins import
themselves leads to circular imports.

**Metadata rides along.** `@SnackMenu.component(name="tuna surprise", vegetarian=False)` stores the arguments in a
`ComponentRegistration` next to the component; `_on_component_register(registration)` sees each one as it arrives,
and the `components` list keeps them all.

**Overriding a container happens before the first component.** Registering a component requests the container's
instance, which freezes it. An application that swaps the container for a subclass declares the override before the
collector runs.

## Read on

* [Containers](../features/containers.md) and [Collector](../features/utilities.md#collector), the feature pages
* [README: Containers](../../README.md#containers), the full rules and `ComponentRegistration`
