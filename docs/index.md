# smalldi documentation

The [README](../README.md) introduces each feature with an example and its rules. Two sections start from what you
want to do: [Features](features/index.md) describes each building block on one short page with a runnable example,
and [Use cases](use-cases/index.md) shows complete programs for wiring an application, swapping implementations,
testing, plugins and threads. The pages below describe the objects behind the registry and how they behave across
contexts and threads.

| Page | What it covers |
|------|----------------|
| [architecture.md](architecture.md) | The objects that make up the injector: `Injector`, the context registry and tree, execution slices, `InjectionContext`, `LazySingleton`, `InterfaceResolver` and the interface bindings, with an entity diagram and a walk-through of `Injector.get_instance(T)` and `@Injector.override`. |
| [contexts.md](contexts.md) | Injection contexts: the five kinds with a before/after diagram of what each shares with its parent, the per-slice context stacks for threads, `ContextAwareThread` and asyncio tasks, how `__exit__` unwinds the stack, the import caveat and the coroutine limitation. |
| [concurrency.md](concurrency.md) | The locking model, freeze-on-lookup, the override refusals, and which circular dependencies are detected. |

Related:

* [README: Contexts](../README.md#contexts), the example and the rules in short form
* [CHANGELOG](../CHANGELOG.md), what each release added or changed
* [Migration](migration/index.md), which guide to follow when upgrading from 0.2 or 0.3
* [llms.txt](../llms.txt), the whole API in one page for language models
