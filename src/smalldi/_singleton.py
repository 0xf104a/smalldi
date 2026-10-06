from threading import RLock

# Single lock for creating all singletons. Creation is rare, and one lock makes a dependency cycle
# visible to the creating thread (it raises instead of deadlocking, even when threads race on the
# cycle from different ends). Lock order: this lock may be held while acquiring other library locks,
# never the other way round.
_creation_lock = RLock()


class LazySingleton:
    """
    A singleton that is created on first access. Once created it is frozen.
    If the created instance has `_on_singleton_created` method, it is called right after creation,
    before the instance is visible to other threads.
    """
    def __init__(self, cls: type):
        self.cls = cls
        self._instance = None
        self._ready = False
        self._creating = False

    def get(self):
        """
        Returns the instance, creating it on first call.
        :return: singleton instance
        :raises TypeError: on circular dependency
        """
        if self._ready:
            return self._instance
        with _creation_lock:
            if self._instance is not None:
                # Ready, or re-entered from _on_singleton_created in the creating thread
                return self._instance
            if self._creating:
                raise TypeError(f"Circular dependency while creating singleton {self.cls!r}")
            self._creating = True
            try:
                self._instance = self.cls()
            finally:
                self._creating = False
            try:
                on_created = getattr(self._instance, "_on_singleton_created", None)
                if on_created is not None:
                    on_created()
            finally:
                # The instance exists even if the hook failed; don't create a second one
                self._ready = True
            return self._instance

    @property
    def instance(self):
        """
        The instance if it was created, otherwise None. Never creates it.
        """
        return self._instance if self._ready else None

    @property
    def frozen(self) -> bool:
        # Generally, if lazy singleton has instance, it means some dependent class already injected it
        return self._ready or self._creating or self._instance is not None
