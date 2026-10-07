"""
Imports every module of a package, so that the decorators in them run.
"""
import importlib
import pkgutil

from smalldi.decorator import staticclass


@staticclass
class Collector:
    """
    Static class that imports all modules of a package to trigger their decorators.

    Registration with `@Injector.singleton`, `@Injector.interface` and
    `@Container.component` happens when the defining module is imported.
    `Collector.collect_from_package` imports every module of a package, so
    nothing stays unregistered because nobody imported it.

    Intended use: at startup, from a top-level module of the program, before
    anything is injected. Calling it from a module that the collected
    modules import themselves leads to circular imports.
    """
    @staticmethod
    def collect_from_package(package_name: str):
        """
        Imports a package and then every module and subpackage found under it, in `pkgutil.walk_packages` order.

        :param package_name: importable name of the package
        :return: None
        :raises ModuleNotFoundError: if the package or one of its modules can't be found
        :raises ImportError: if importing the package or one of its modules fails
        :raises AttributeError: if `package_name` names a plain module, which has no `__path__`
        :raises Exception: any exception raised while a module is imported propagates unchanged
        """
        package = importlib.import_module(package_name)

        for _, module_name, _ in pkgutil.walk_packages(
                package.__path__,
                prefix=package.__name__ + "."
        ):
            importlib.import_module(module_name)
