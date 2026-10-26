"""
Where a decorated function is defined: an instance method, a classmethod, a staticmethod, or none of these.

`@threadsafe` chooses the lock guarding a function by its placement, and `@oneshot` the key
its result is stored under.
"""
import enum
import inspect


class FunctionPlacement(enum.Enum):
    """
    Where a function decorated with `@threadsafe` or `@oneshot` is defined, which
    determines the lock guarding it or the key its result is kept under.
    """
    INSTANCE_LEVEL = enum.auto()
    CLASS_LEVEL = enum.auto()
    STATIC_LEVEL = enum.auto()

    @classmethod
    def from_function(cls, fn: object) -> "FunctionPlacement | None":
        """
        Detects the placement of a function from the object found in the class body.
        Plain functions are told apart by `__qualname__`: a function defined
        directly in a class body is an instance method.

        :param fn: function, `staticmethod` or `classmethod` object
        :return: placement of the function, or None if it isn't defined in a class body
        """
        if isinstance(fn, staticmethod):
            return cls.STATIC_LEVEL
        if isinstance(fn, classmethod):
            return cls.CLASS_LEVEL
        if inspect.isfunction(fn):
            # Plain function: either a def directly in a class body (instance-level)
            # or a module-level / nested function that isn't a method at all.
            parent, _, _ = fn.__qualname__.rpartition(".")
            if parent and not parent.endswith("<locals>"):
                return cls.INSTANCE_LEVEL
            return None
        return None
