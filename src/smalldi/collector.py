import importlib
import pkgutil

from smalldi.wrappers import staticclass


@staticclass
class Collector:
    """
    Collector is responsible for searching for components in the container
    You may inject it into your function and invoke the ` search ` method to import modules and trigger
    decorators.
    Note that you should call this from a top-level module which is not imported by any of the modules
    which may import the current module, otherwise you may get exception due to circular imports.
    """
    @staticmethod
    def collect_from_package(package_name: str):
        """
        Sequentially imports all modules from the given package
        to trigger decorators in them.
        :return: None
        """
        package = importlib.import_module(package_name)

        for _, module_name, _ in pkgutil.walk_packages(
                package.__path__,
                prefix=package.__name__ + "."
        ):
            importlib.import_module(module_name)