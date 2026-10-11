# Concurrency

`Injector` may be used from several threads. This page states the locking model as the docstrings of `Injector`,
`LazySingleton`, `_LazyInterfaceImpl`, `InterfaceResolver` and `ContextTree` describe it, and what follows from it.

## Locks

| Lock | Guards | Held by |
|------|--------|---------|
| `Injector.__class_mutex__`, reentrant | the registry of the current context and the per-slice context stacks | `singleton`, `interface`, `override`, `implements`, `is_singleton`, `is_interface` and `get_context` for the whole call; `inject` while it checks each `Provide[T]` parameter at decoration time; the decorators returned by `override` and `implements` while they bind; `__enter__` and `__exit__` of the context manager; `get_instance` only while it looks the singleton or interface binding up and freezes it |
| `LazySingleton.__instance_mutex__`, reentrant (state lock) | the override class, the override mark, the frozen flag | every `LazySingleton` method except `get_instance()`, for the whole call; `get_instance()` only to set the frozen flag |
| `LazySingleton._build_lock`, reentrant (build lock) | the constructor call and the instance | `get_instance()` while it checks for an instance and, if needed, runs the constructor; nothing else |
| `_LazyInterfaceImpl.__instance_mutex__`, reentrant | one interface's implementation, override and frozen flag | `override()`, `implement()`, `rebind()` and `resolve()` for the whole call |
| `InterfaceResolver.__instance_mutex__`, reentrant | the dict of interfaces | every resolver method for the whole call |
| `ContextTree` instance lock, reentrant | the slice-to-node dict | every `ContextTree` method for the whole call |
| `InjectionContextRegistry._watched_mutex` | the set of watched slices | while a slice is added to or removed from the set |

The invariant: **no lock that guards the registry or a binding is held while a constructor runs or while another
instance is requested.** `Injector.get_instance` releases the class mutex before it asks the `LazySingleton` for the
instance, and `LazySingleton.get_instance()` holds only its own build lock while the constructor runs. A constructor
decorated with `@Injector.inject` therefore takes the class mutex again, briefly, for each of its dependencies, and
waits on the build locks of the singletons it depends on.

An `InjectionContext` has no lock of its own. One context may be current for several slices at once, through
`PRESERVE`, `SHALLOW`, `Injector.foreign_context` and `ContextAwareThread`, and that is safe only because every
access to it goes through `Injector` under the class mutex.

## Freeze on lookup

A request for an instance freezes what it looks up, under the class mutex, together with the lookup:

* `Injector.get_instance(Singleton)` freezes the singleton's `LazySingleton`;
* `Injector.get_instance(Interface)` freezes the interface's binding, then the `LazySingleton` it resolves to, the
  override if there is one and the implementation otherwise. The binding stays frozen even if it turns out to have
  neither.

Freezing happens before the constructor runs, so a singleton is frozen while its constructor is in flight and stays
frozen if the constructor raised; a failed construction leaves no instance, and the next request runs the constructor
again. Nothing unfreezes a target: a `RESET` or `STACK` context gives it a fresh, unfrozen copy instead (see
[contexts.md](contexts.md)). Reading the deprecated `Injector.singletons_available` instantiates and freezes every
registered singleton.

Because the freeze and the lookup are one step under the class mutex, and every override runs under the same mutex,
an override racing a request for its target either runs entirely before the request and wins, or entirely after it
and is refused. No constructor ever runs inside a `LazySingleton` that an override discarded.

## Override refusals

Every check runs before anything is bound, so a refused override leaves the registry and every binding unchanged.

| Raised | When |
|--------|------|
| `SingletonFrozenError` | the target singleton or interface is frozen, that is an instance was requested through it |
| `SingletonFrozenError` | the target is a singleton and the overriding class is frozen without an instance: its constructor is running in another thread, or it failed |
| `RuntimeError` | the target singleton already has an override |
| `TypeError` | the target interface already has an override |
| `TypeError` | the overriding class is not a registered singleton, not a subclass of the target, or is the target itself |
| `TypeError` | the override would form a chain: the target singleton is an override itself, or the overriding class is overridden by another class |
| `TypeError` | the overriding class is the interface's implementation |

An overriding class that is frozen *with* an instance is accepted: the shared `LazySingleton` takes over that
instance and the frozen state, so the target resolves to the instance that already exists.

`@Injector.implements` is refused with `SingletonFrozenError` when the interface is frozen and has no override; a
frozen interface that already has an override still accepts its first implementation, since the override keeps
winning.

## Exactly-once construction

Each singleton is constructed at most once per `LazySingleton`: the first `get_instance()` runs the constructor under
the build lock, and concurrent callers wait on that lock and receive the same instance. In a `RESET` or `STACK`
context the singleton is a different `LazySingleton`, so it is constructed once more, there.

## What is detected and what is not

* **Detected: a circular dependency within one thread.** `LazySingleton.get_instance()` records the calling thread
  while the constructor runs. If the same thread asks for that singleton again before the constructor returned,
  directly or through its dependencies, it raises `RuntimeError`.
* **Not detected: a dependency cycle spanning several threads.** Thread A constructs `X`, which asks for `Y`;
  thread B constructs `Y`, which asks for `X`. Each waits on the other's build lock. Nothing in the library inspects
  the other thread's path, so this deadlocks.
* **Not detected: a constructor waiting for another thread that needs the singleton being constructed.** A
  constructor that blocks on `join`, `Event.wait`, `Future.result` or similar until a thread finishes, when that
  thread, directly or through its dependencies, requests the singleton under construction, deadlocks the same way.

`test_cross_thread_circular_dependency_does_not_deadlock` in `src/tests/test_injector_concurrency.py` documents the
second case and is skipped.
