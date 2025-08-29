import inspect
from typing import TypeVar, Generic, get_origin, get_args, Iterator, Callable, Any, TypeAlias, Annotated

_T = TypeVar("_T")

class _Provide(Generic[_T]):
    """Provide annotation tells smalldi to find instance of T and inject it into function"""
    @staticmethod
    def unwrap(tp: object) -> type:
        """
        Unwraps annotation to get inner type.
        :param tp: annotation itself
        :return: inner type T
        """
        origin = get_origin(tp)
        if origin is _Provide:
            (inner,) = get_args(tp)
            return inner

        if origin is Annotated:
            args = get_args(tp)
            inner, *meta = args
            if any(m is Provide for m in meta):
                return inner

        raise TypeError(f"Expected Provide[T], got {tp!r}")

    @staticmethod
    def iter_annotations(func: Callable) -> Iterator[Any]:
        """
        Provides an iterator that extracts and yields annotations of type `Provide`
        from the parameters of a given function's signature.
        :param func: The function whose parameter annotations will be inspected.
        :type func: Callable
        :return: An iterator over the unwrapped annotations of type `Provide` found
            in the function's parameters.
        :rtype: Iterator[str, Any]
        """
        signature = inspect.signature(func)
        for name, param in signature.parameters.items():
            try:
                inner = _Provide.unwrap(param.annotation)
                yield name, inner
            except TypeError:
                continue

Provide: TypeAlias = Annotated[_T, _Provide]
