"""
A set whose operations are serialized by a lock, used by `LazySingleton` to track constructing threads.
"""
from typing import TypeVar

from smalldi.concurrency import threadsafe

_T = TypeVar('_T')

class AtomicSet:
    """
    Set whose methods are each guarded by a reentrant lock stored on the instance.

    Only the methods below are serialized; `value` itself is a plain set.

    :ivar value: the underlying set
    """
    def __init__(self, value: set[_T] | None = None):
        """
        :param value: initial set, used as-is (not copied); None or an empty set means a new empty set
        """
        if not value:
            value = set()
        self.value = value

    @threadsafe
    def check_and_add(self, item: _T) -> bool:
        """
        Adds an item and tells whether it was already present.

        :param item: item to add
        :return: True if `item` was in the set before the call
        """
        result = item in self.value
        self.value.add(item)
        return result

    @threadsafe
    def check_and_remove(self, item: _T) -> bool:
        """
        Removes an item and tells whether it was present. Not used by the package.

        :param item: item to remove
        :return: True if `item` was in the set before the call
        :raises KeyError: if `item` isn't in the set
        """
        result = item in self.value
        self.value.remove(item)
        return result

    @threadsafe
    def check(self, value: _T) -> bool:
        """
        Tells whether an item is in the set. Not used by the package.

        :param value: item to look for
        :return: True if `value` is in the set
        """
        return value in self.value

    @threadsafe
    def add(self, value: _T) -> None:
        """
        Adds an item. Not used by the package.

        :param value: item to add
        """
        self.value.add(value)

    @threadsafe
    def remove(self, value: _T) -> None:
        """
        Removes an item.

        :param value: item to remove
        :raises KeyError: if `value` isn't in the set
        """
        self.value.remove(value)
