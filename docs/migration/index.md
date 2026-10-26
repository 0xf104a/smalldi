# Migration guides

Pick the guide for the version you are upgrading from: each one lists the breaking changes, the behaviour changes
that need no code change, the features that became available, and a checklist in the order to apply it. Upgrading
from 0.2 straight to 0.4 is one step: [0.2 → 0.4](0.2-to-0.4.md) describes the final 0.4 behaviour directly and is
not the two other guides glued together.

* [0.2 → 0.3](0.2-to-0.3.md): lazy singletons, the deprecated `Injector.singletons_available`, interfaces and overrides
* [0.3 → 0.4](0.3-to-0.4.md): injection contexts, `Provide[T]` in coroutine functions, override refusals
* [0.2 → 0.4](0.2-to-0.4.md): the direct path from 0.2 to 0.4

Upgrading from 0.4 to 0.5 needs no guide: 0.5 changes nothing for 0.4 code. One consequence of the additions is
that `from smalldi import *` also imports the shorthands `singleton`, `interface`, `implements`, `override`,
`inject`, `issingleton` and `isinterface`, which can shadow names of the same spelling in the importing module;
the [0.5.0 section of the changelog](../../CHANGELOG.md#050) lists everything added.
