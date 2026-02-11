import functools

from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.2.0"
__all__ = ["Injector", "Provide"]

@staticclass
class Injector:
    """
    The injector class handles all the dependency injections.
    """
    singletons_available = {}

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.
        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        """
        kwargs_ext = dict()
        for name, tp in _Provide.iter_annotations(fn):
            if tp not in cls.singletons_available:
                raise TypeError(f"Singleton {tp} is not available")
            kwargs_ext[name] = cls.singletons_available[tp]

        @functools.wraps(fn)
        def wrapped_fn(*args, **kwargs):
            for name, value in kwargs_ext.items():
                if name not in kwargs:
                    kwargs[name] = value
            return fn(*args, **kwargs)

        return wrapped_fn

    @classmethod
    def singleton(cls, target_cls):
        """
        Marks class as singleton.
        Singleton classes are instantiated only once by the injector.
        Also their __init__ function should have no arguments or be annotated
        with @Injector.inject, so it would
        :param target_cls: Class which to be marked as injectable singleton
        :return: None
        """
        cls.singletons_available[target_cls] = target_cls()
        return target_cls
