import inspect
import threading
from typing import Optional, TypeVar

_T = TypeVar("_T")


class InterfaceFrozenError(Exception):
    """The implementation was already looked up; the binding can no longer change."""

    def __init__(self, which: type, resolved_target: type, rebind_target: type):
        super().__init__(f"{which!r} was already resolved to "
                         f"{resolved_target!r}; cannot rebind to {rebind_target!r}")
        self.resolved_target = resolved_target
        self.rebind_target = rebind_target
        self.interface = which


class InterfaceTable:
    """
    Thread-safe table mapping interfaces to their implementations.
    A binding may be replaced until it is first looked up; after that it is frozen,
    because whoever looked it up already holds the old implementation.
    """
    def __init__(self) -> None:
        self._interface_impls: dict[type, type] = {}
        self._frozen_interfaces: set[type] = set()
        self._lock = threading.Lock()

    def is_frozen(self, interface: type) -> bool:
        """
        Checks whether binding of interface was already looked up and can no longer change.
        :param interface: interface to check
        :return: True if binding is frozen
        """
        with self._lock:
            return interface in self._frozen_interfaces

    def set_interface_impl(self, interface: type[_T], impl: type[_T]) -> None:
        """
        Binds implementation to interface, replacing previous binding if it is not frozen.
        Binding the same implementation again is a no-op.
        :param interface: interface (usually an abstract class)
        :param impl: concrete subclass of interface
        :raises TypeError: if impl is not a concrete subclass of interface
        :raises InterfaceFrozenError: if binding was already looked up and impl differs
        """
        if not inspect.isclass(interface):
            raise TypeError(f"Interface must be a class, got {interface!r}")
        if not inspect.isclass(impl):
            raise TypeError(f"Implementation must be a class, got {impl!r}")
        if impl is interface or not issubclass(impl, interface):
            raise TypeError(f"{impl!r} does not implement {interface!r}")
        if inspect.isabstract(impl):
            missing = ", ".join(sorted(impl.__abstractmethods__))
            raise TypeError(
                f"{impl!r} leaves abstract members of {interface!r}: {missing}"
            )
        with self._lock:
            current = self._interface_impls.get(interface)
            if current is impl:
                return
            if interface in self._frozen_interfaces:
                raise InterfaceFrozenError(interface, current, impl)
            self._interface_impls[interface] = impl

    def get_interface_impl(self, interface: type[_T]) -> Optional[type[_T]]:
        """
        Looks up implementation of interface and freezes the binding if one exists.
        :param interface: interface to look up
        :return: bound implementation or None if interface is not bound
        """
        with self._lock:
            impl = self._interface_impls.get(interface)
            if impl is not None:
                self._frozen_interfaces.add(interface)
            return impl
