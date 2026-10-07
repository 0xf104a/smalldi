"""
The `Provide[T]` annotation that marks a parameter for injection, and the helpers reading it.
"""
import inspect
from typing import TypeVar, Generic, get_origin, get_args, Iterator, Callable, Any, TypeAlias, Annotated

_T = TypeVar("_T")

class _Provide(Generic[_T]):
    """
    Marker behind `Provide[T]`: a parameter annotated with it receives the instance of `T`.

    `Provide` is `Annotated[T, _Provide]`, so the marker travels inside
    `Annotated` metadata. `_Provide[T]` itself is recognised too.
    """
    @staticmethod
    def unwrap(tp: object) -> type:
        """
        Returns the `T` of a `Provide[T]` annotation.

        :param tp: annotation to unwrap: `_Provide[T]`, or `Annotated[T, ...]` with `_Provide` among its metadata
        :return: inner type `T`
        :raises TypeError: if `tp` is neither form
        """
        origin = get_origin(tp)
        if origin is _Provide:
            (inner,) = get_args(tp)
            return inner

        if origin is Annotated:
            args = get_args(tp)
            inner, *meta = args
            if any(m is _Provide for m in meta):
                return inner

        raise TypeError(f"Expected Provide[T], got {tp!r}")

    @staticmethod
    def iter_annotations(func: Callable) -> Iterator[Any]:
        """
        Yields `(name, T)` for every parameter of a function annotated with `Provide[T]`.

        Parameters with other annotations, or without one, are skipped.

        :param func: function whose signature is inspected
        :return: iterator of `(parameter name, T)` pairs, in signature order
        :raises ValueError: from `inspect.signature`, if no signature can be provided for `func`
        :raises TypeError: from `inspect.signature`, if `func` is not a supported callable
        """
        signature = inspect.signature(func)
        for name, param in signature.parameters.items():
            try:
                inner = _Provide.unwrap(param.annotation)
                yield name, inner
            except TypeError:
                continue

Provide: TypeAlias = Annotated[_T, _Provide]
