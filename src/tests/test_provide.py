from typing import Annotated, List

from smalldi import Injector, Provide


def test_provide_annotation_is_injected(reset_injector):
    """A parameter annotated with Provide[T] receives the instance of T"""
    @Injector.singleton
    class Service:
        pass

    @Injector.inject
    def fn(service: Provide[Service]):
        return service

    assert fn() is Injector.get_instance(Service)


def test_provide_inside_annotated_is_injected(reset_injector):
    """Provide is an Annotated alias, so Annotated[T, ...] carrying its marker is recognised too"""
    @Injector.singleton
    class Service:
        pass

    marker = Provide[Service].__metadata__[0]

    @Injector.inject
    def fn(service: Annotated[Service, "doc", marker]):
        return service

    assert fn() is Injector.get_instance(Service)


def test_plain_annotations_are_left_alone(reset_injector):
    """Parameters without Provide, including plain and generic annotations, are not injected"""
    @Injector.singleton
    class Service:
        pass

    @Injector.inject
    def fn(a: str, b: List[int], c: Annotated[int, "meta"], service: Provide[Service]):
        return a, b, c, service

    a, b, c, service = fn("x", [1], c=2)
    assert (a, b, c) == ("x", [1], 2)
    assert isinstance(service, Service)


def test_function_without_provide_annotations(reset_injector):
    """A function without Provide annotations is wrapped without injecting anything"""
    @Injector.inject
    def func(a: str, b: int):
        return a, b

    assert func("x", 1) == ("x", 1)
    assert func.__name__ == "func"
