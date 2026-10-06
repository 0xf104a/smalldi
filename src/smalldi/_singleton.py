from typing import Any, Type

from smalldi.concurrency import threadsafe


class SingletonFrozenError(Exception):
    pass

class LazySingleton:
    def __init__(self, cls: Type, override: Type | None):
        self.cls = cls
        self.override_cls = None
        self.instance = None
        if override is not None:
            self._validate_override(cls, override)
        self.override_cls = override

    def _validate_override(self, base: Type, override: Type):
        if base is override:
            return
        if self.frozen:
            raise SingletonFrozenError("Cannot override a frozen singleton")
        if not issubclass(override, base):
            raise TypeError(f"Override {override} is not a subclass of {base}")

    @threadsafe
    def get_instance(self) -> Any:
        if self.instance is None:
            if self.override_cls is not None:
                self.instance = self.override_cls()
            else:
                self.instance = self.cls()
        return self.instance

    @threadsafe
    def override(self, override: Type):
        if self.override_cls is override:
            return
        if self.override_cls is not None:
            raise TypeError("Cannot override an already overridden singleton")
        self._validate_override(self.cls, override)
        self.override_cls = override

    @property
    def frozen(self) -> bool:
        return self.instance is not None

