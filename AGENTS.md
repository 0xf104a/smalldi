# smalldi: notes for coding agents

smalldi is an annotation-driven dependency-injection library for Python (>=3.11) with zero runtime dependencies.
The package lives in `src/smalldi/`, the tests in `src/tests/`.

## Module layout

- `src/smalldi/__init__.py`: `Injector` (the static registry and its decorators `singleton`, `interface`, `implements`, `override`, `inject`), `Injector.context`, which dispatches on its argument to the kind path (an `InjectionSubcontextType` member, `RESET` by default) or the declared path (an `InjectionContextSingletonOverride` subclass or instance), `Injector.get_instance`, `Injector.is_singleton`, `Injector.is_interface`, the deprecated `Injector.singletons_available` descriptor, and the public re-exports `Provide` and `SingletonFrozenError`.
- `src/smalldi/_singleton.py`: `LazySingleton`, the lazily built single instance of a registered class or of the class overriding it, with freezing and the circular-dependency check; `SingletonFrozenError`.
- `src/smalldi/_interfaces.py`: `InterfaceResolver`, the registry of interfaces, and `_LazyInterfaceImpl`, one interface's binding to the `LazySingleton` objects implementing and overriding it.
- `src/smalldi/context.py`: `InjectionContext`, `InjectionSubcontextType`, `InjectionContextManager`, and `InjectionContextSingletonOverride`, the dataclass declaration of a `SHALLOW` child with singletons of its own; its fields are concrete classes only.
- `src/smalldi/_context/__init__.py`: `InjectionContextRegistry`, the per-slice current context, with a `ResourceWarning` for contexts left open.
- `src/smalldi/_context/tree.py`: `ContextTree`, the per-slice context stacks.
- `src/smalldi/thread.py`: `ContextAwareThread`.
- `src/smalldi/annotation.py`: `Provide[T]` (an `Annotated` alias) and the helpers that read it from a function signature.
- `src/smalldi/asynchronous.py`: `wrap_coroutine_function`, the coroutine-function wrapper `Injector.inject` returns for an `async def` function.
- `src/smalldi/container.py`: `Container`, a singleton base class collecting components registered with `@MyContainer.component`, and `ComponentRegistration`.
- `src/smalldi/collector.py`: `Collector.collect_from_package`, which imports every module of a package so its decorators run.
- `src/smalldi/concurrency.py`: `@synchronized`, `@threadsafe` and the `mutex` decorator factory, the reentrant-lock helpers used throughout the package.
- `src/smalldi/decorator.py`: `staticclass`, which makes a class uninstantiable.
- `src/smalldi/atomic.py`: `AtomicSet`, a lock-guarded set used by `LazySingleton` to track the threads inside a constructor.
- `src/smalldi/wrappers.py`: compatibility alias re-exporting `staticclass` from `smalldi.decorator`.
- `src/smalldi/py.typed`: marker that the package is typed.

## Documentation site

The site at https://smalldi.readthedocs.io/ is built by [Zensical](https://zensical.org/) from a staged copy of the
Markdown files, so the files themselves stay where GitHub renders them:

- `zensical.toml`: the site configuration; `docs_dir` is `_docs`, the staged copy, which is git-ignored.
- `.github/scripts/stage_docs.py`: writes `_docs/`: README.md as the landing page `index.md`, `docs/` as the `docs/`
  section, CHANGELOG.md, llms.txt, and a generated `api.md` of mkdocstrings directives for every public module. It
  rewrites links in the copies only: links from `docs/` up to README.md point to `index.md`, and README links to
  repository files through GitHub point to the pages in the site.
- `docs/assets/material3.css`: the Material 3 token adapter, the tonal palettes of f104a.io mapped onto the theme's
  `--md-*` variables, plus the component shapes.
- `docs/requirements.txt`: the pinned site generator, installed by Read the Docs and the CI docs job only; it is not
  a runtime dependency.
- `.readthedocs.yaml`: checks out the release to document, installs the requirements, stages, builds with
  `zensical build --clean --strict` and copies `site/` to the Read the Docs output directory.
- `.github/scripts/checkout_latest_release.sh`: the `post_checkout` job. The version `latest` documents the latest
  release, not the head of master: for that version the script fetches the tags and checks out the highest release
  tag (`MAJOR.MINOR.PATCH`, optional `v` prefix, no pre-releases); every other version builds the commit it was
  cloned at. A release that predates the site cancels the build (exit status 183), which keeps the published
  `latest`. Read the Docs rebuilds `latest` on pushes to master only, so the `docs-latest` job of
  `.github/workflows/publish.yaml` triggers the rebuild on a release through the Read the Docs API with the
  repository secret `READTHEDOCS_TOKEN`; without the secret it warns instead.

Build locally with `python .github/scripts/stage_docs.py && zensical build --strict`, or `zensical serve` after
staging; re-run the staging script after editing a page. Python-Markdown needs a blank line before a list that
follows a paragraph, otherwise the list renders inline; GitHub is lenient about that, the site is not.

## Running the tests

```shell
cd src && python -m pytest
```

Tests need no installation beyond pytest: `src/` is the import root. `src/tests/README.md` lists what each test module covers.

## Design invariants

- Registries are per `InjectionContext`. Within one context there is one `LazySingleton` per registered class, owned by the context's `singletons_available`; an override aliases registry keys, so the overridden class and the overriding class map to one `LazySingleton` object. Interface bindings (`_LazyInterfaceImpl`) refer to those objects and never create their own.
- Overrides are not transitive. No code follows chains of bindings or walks graphs: there is no recursive graph traversal and no cycle-detection walk. Resolution is at most one interface lookup followed by one `LazySingleton`, which instantiates its override class if set, else its own class; there is no delegation.
- Validation happens before mutation: every check of a binding or registration runs before anything changes, so a failed call leaves the registry and every binding as they were.
- Frozen means frozen. A singleton is frozen the first time its instance is requested, an interface the first time an instance is requested through it, even if that request failed. Nothing unfreezes a target; a frozen target accepts no override, and an interface accepts an implementation after freezing only if it already has an override. `Injector.get_instance` freezes the looked-up singleton, or the interface and the singleton it resolves to, under the class mutex together with the lookup. An overriding class that is frozen shares its instance with the target; if it is frozen without an instance (constructor in flight or failed), the override raises `SingletonFrozenError` and never waits for that constructor.
- Decorator order: `@Injector.override(...)` and `@Injector.implements(...)` go above `@Injector.singleton`, because both require the decorated class to be a registered singleton already.
- No lock that guards the registry (`Injector.__class_mutex__`, the resolver lock) or a binding (a `LazySingleton` or `_LazyInterfaceImpl` state lock) is held while a constructor runs or while another instance is requested. Only the singleton's own build lock is held during construction.

## Known threading limitation

Circular dependencies are detected within one thread and raise `RuntimeError`. Two cases are not detected and may deadlock: a dependency cycle that spans several threads, and a constructor that waits (`join`, `Event.wait`, `Future.result`, ...) for another thread which needs the singleton being constructed, directly or through its dependencies. `test_cross_thread_circular_dependency_does_not_deadlock` in `src/tests/test_injector_concurrency.py` is skipped for this reason. Opt-in detection is planned; don't add graph walks to the resolution path to get it.

## House rules

- Zero runtime dependencies. `dependencies = []` in `pyproject.toml` stays empty; the standard library is enough.
- Deprecate before removing public API. A deprecated name keeps working and warns with `DeprecationWarning`; removal happens no earlier than 1.0.0.
- Tests use the public API only. The three specification files define the semantics: `src/tests/test_override_rules.py`, `src/tests/test_interface_bindings.py` and `src/tests/test_injector_concurrency.py`. Where the library disagrees with them, the library is what changes.
- Docs describe current behaviour only. README, `llms.txt` and this file contain no development history (no "now", "no longer", "used to", "previously"); history lives in `CHANGELOG.md`.
- README examples start with one plain technical sentence stating the concept, then the story example, then a `Rules:` list in plain technical language with no story in it. Every example runs as-is; error cases are `try/except` blocks printing the caught exception type.
- Cast for README examples: Pusheen (a chubby grey tabby who loves snacks, cookies and naps; siblings Stormy and Pip) is the only cast for new examples; don't introduce any other characters, from any franchise. Existing examples keep their characters and are not recast.