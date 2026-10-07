from typing import TypeVar

from smalldi.concurrency import threadsafe

_T = TypeVar('_T')

class AtomicSet:
    def __init__(self, value: set[_T] | None = None):
        if not value:
            value = set()
        self.value = value

    @threadsafe
    def check_and_add(self, item: _T) -> bool:
        result = item in self.value
        self.value.add(item)
        return result

    @threadsafe
    def check_and_remove(self, item: _T) -> bool:
        result = item in self.value
        self.value.remove(item)
        return result

    @threadsafe
    def check(self, value: _T) -> bool:
        return value in self.value

    @threadsafe
    def add(self, value: _T) -> None:
        self.value.add(value)

    @threadsafe
    def remove(self, value: T) -> None:
        self.value.remove(value)
