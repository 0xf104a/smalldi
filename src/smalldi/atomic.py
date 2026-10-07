from smalldi import threadsafe


class AtomicSet[T]:
    def __init__(self, value: set[T] | None = None):
        if not value:
            value = set()
        self.value = value

    @threadsafe
    def check_and_add(self, item: T) -> bool:
        result = item in self.value
        self.value.add(item)
        return result

    @threadsafe
    def check_and_remove(self, item: T) -> bool:
        result = item in self.value
        self.value.remove(item)
        return result

    @threadsafe
    def check(self, value: T) -> bool:
        return value in self.value

    @threadsafe
    def add(self, value: T) -> None:
        self.value.add(value)

    @threadsafe
    def remove(self, value: T) -> None:
        self.value.remove(value)
