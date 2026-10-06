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


class InterfaceAlreadyBoundError(Exception):
    """The interface already has an implementation (or override) bound in the same slot."""

    def __init__(self, which: type, bound_target: type, rebind_target: type, slot: str):
        hint = "; use @Injector.override to replace it" if slot == "implementation" else ""
        super().__init__(f"{which!r} already has {slot} {bound_target!r}; "
                         f"cannot bind {rebind_target!r}{hint}")
        self.bound_target = bound_target
        self.rebind_target = rebind_target
        self.interface = which
        self.slot = slot


class InterfaceTable:
    """
    Thread-safe table mapping interfaces to their implementations.
    Each interface has a baseline implementation and at most one override; the override,
    if present, wins. Each slot can be set only once (setting the same class again is a no-op).
    Once an interface is looked up its resolved implementation is frozen and can no longer
    change, because whoever looked it up already holds it.
    """
    def __init__(self) -> None:
        self._baselines: dict[type, type] = {}
        self._overrides: dict[type, type] = {}
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
        Binds baseline implementation to interface.
        :param interface: interface (usually an abstract class)
        :param impl: concrete subclass of interface
        :raises TypeError: if impl is not a concrete subclass of interface
        :raises InterfaceAlreadyBoundError: if another baseline is already bound
        :raises InterfaceFrozenError: if this would change an already looked up implementation
        """
        self._bind(self._baselines, "implementation", interface, impl)

    def set_interface_override(self, interface: type[_T], impl: type[_T]) -> None:
        """
        Overrides implementation of interface. Override takes precedence over the baseline
        and may be set before or after it.
        :param interface: interface (usually an abstract class)
        :param impl: concrete subclass of interface
        :raises TypeError: if impl is not a concrete subclass of interface
        :raises InterfaceAlreadyBoundError: if another override is already bound
        :raises InterfaceFrozenError: if this would change an already looked up implementation
        """
        self._bind(self._overrides, "override", interface, impl)

    def get_interface_impl(self, interface: type[_T]) -> Optional[type[_T]]:
        """
        Looks up the implementation of the interface and freezes the binding if one exists.
        :param interface: interface to look up
        :return: override if set, otherwise baseline, or None if interface is not bound
        """
        with self._lock:
            impl = self._effective_impl(interface)
            if impl is not None:
                self._frozen_interfaces.add(interface)
            return impl

    def _effective_impl(self, interface: type) -> Optional[type]:
        return self._overrides.get(interface, self._baselines.get(interface))

    def _bind(self, slots: dict[type, type], slot: str, interface: type, impl: type) -> None:
        self.check_impl(interface, impl)
        with self._lock:
            current = slots.get(interface)
            if current is impl:
                return
            if current is not None:
                raise InterfaceAlreadyBoundError(interface, current, impl, slot)
            if interface in self._frozen_interfaces:
                resolved = self._effective_impl(interface)
                slots[interface] = impl
                if self._effective_impl(interface) is not resolved:
                    del slots[interface]
                    raise InterfaceFrozenError(interface, resolved, impl)
                return
            slots[interface] = impl

    @staticmethod
    def check_impl(interface: type, impl: type) -> None:
        """
        Checks that impl is a concrete subclass of interface.
        :param interface: interface (usually an abstract class)
        :param impl: class to check
        :raises TypeError: if impl is not a concrete subclass of interface
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
