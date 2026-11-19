# morphtest

A test framework where test matrices are not written by hand but **resolved by a SAT
solver**. Test cases and the things they run on (devices, configurations, protocols, …)
are components that declare what they need; morphtest enumerates every consistent
combination and picks one best fit per combination you are interested in.

## Installation

```bash
uv add git+https://github.com/baltech-ag/morphtest.git
```

Requires Python 3.11 or newer.

## Usage

### 1. Test cases

Components inherit from `morphtest.Component` and declare their dependencies with
`Dependency[...]`. Test cases inherit from `morphtest.TestCase` and implement `run()`.
A `TestSuite` resolves one test per valid combination:

```python
import abc

from morphtest import Component, Dependency, TestCase, TestSuite, if_not_overwritten


class Chip(Component, abc.ABC): ...


class Chip_None(Chip): ...


class Chip_A(Chip): ...


class Device(Component, abc.ABC):
    chip: Dependency[Chip] = if_not_overwritten(Chip_None)


class Device_Small(Device): ...


class Device_Big(Device):
    chip: Dependency[Chip_A]


class TestCase_OnDevice(TestCase, abc.ABC):
    device: Dependency[Device]

    def run(self) -> None:
        print(f"{self} on {self.device} with {self.device.chip}")


class TestCase_Any(TestCase_OnDevice): ...


class TestCase_NeedsChip(TestCase_OnDevice):
    chip: Dependency[Chip_A]


if __name__ == "__main__":
    TestSuite(TestCase, Device).run()  # every test case on every (matching) device
```

prints (`TestCase_NeedsChip` cannot run on `Device_Small`, which has no `Chip_A`):

```
TestCase_Any on Device_Big with Chip_A
TestCase_NeedsChip on Device_Big with Chip_A
TestCase_Any on Device_Small with Chip_None
```

- The conditions are the components to fan out over: one test per valid combination
  of a `TestCase` and a `Device` implementation. `TestSuite(TestCase_Any, Device)`
  would only run `TestCase_Any`; `TestSuite(Device)` runs one best fitting test case
  per device, as `TestCase` is resolved like every other component.
- `ts.run()` builds every test case and calls its `run()`; an exception fails it and
  stops the suite. Call it only under `if __name__ == "__main__":`, so importing the
  file (e.g. by the `morphtest` command) defines the components without running them.
- Iterating the suite yields the `ComponentDependencySet`s, e.g.
  `TestCase_Any[Chip=Chip_A, Device=Device_Big]`.

### 2. Recommended components and grouping

Components that are not fanned out collapse to a best fit. A test case states which
implementations it prefers with the class variable `recommended_components`.
`group_by` sorts the tests so consecutive tests share expensive components; set it on a
common base so all test cases are sorted the same way:

```python
import abc

from morphtest import Component, Dependency, TestCase, TestSuite


class Device(Component, abc.ABC): ...


class Device_Small(Device): ...


class Device_Big(Device): ...


class TestCase_OnDevice(TestCase, abc.ABC):
    device: Dependency[Device]
    group_by = (Device,)  # all tests of a device run consecutively

    def run(self) -> None:
        print(f"{self} on {self.device}")


class TestCase_A(TestCase_OnDevice): ...


class TestCase_B(TestCase_OnDevice):
    recommended_components = (Device_Small,)


if __name__ == "__main__":
    # all test cases on all devices, grouped by device
    TestSuite(TestCase, Device).run()
    print("---")
    # one device per test case: the best fit
    TestSuite(TestCase).run()
```

prints:

```
TestCase_A on Device_Big
TestCase_B on Device_Big
TestCase_A on Device_Small
TestCase_B on Device_Small
---
TestCase_A on Device_Big
TestCase_B on Device_Small
```

`recommended_components` is applied in list order. Without a recommendation, the
best fit is the solution with the fewest components, then the smallest name. A
subclass replaces the class variable of its base; extend it explicitly with
`recommended_components = (*Base.recommended_components, X)`.

## Component system

### Components and dependencies

- **Components** are classes with the `ComponentMeta` metaclass, usually by inheriting
  from a meta root: `Component`, or your own class with `metaclass=ComponentMeta`
  whose `__init__` accepts the dependencies as keyword arguments. `TestCase` is a root below
  `Component`.
- **Dependencies** are annotated class fields: `device: Dependency[Device]`. They are
  *not* assigned (`device = ...` raises `DependencyAssignmentError`), except to give a
  default via `if_not_overwritten()` (see below).
- Instances get their dependencies as keyword-only arguments
  (`TestCase_Any(device=...)`). `ComponentDependencySet.build()` does this bottom-up.
  Each implementation is instantiated **once per depset** and shared by everything
  depending on it.
- A subclass narrows a dependency by redeclaring the **same field name** with a more
  specific type (`chip: Dependency[Chip_A]`). Using another name for the same dependency
  raises `OverrideDependencyWithDifferentNameError`.
- **Abstract** components (`abc.ABC` among the *direct* bases) are never instantiated;
  selecting one means selecting exactly one of its subclasses. Abstract components
  without subclasses are unselectable. **Concrete** components are everything else.

### Roots and naming

Enforced by the metaclass:

- A **root** is a class directly inheriting from a meta root. Root names must not
  contain `_`.
- Every other component is prefixed with its root name: `Device_Big`, `TestCase_Any`.
- A subclass of a **concrete** component is prefixed with that component's full name:
  `TestCase_Any` → `TestCase_Any_Special` (`ComponentSpecializationPrefixError`).
- **Mixins** (`@mixin`, or a class whose component bases are all mixins) must be abstract
  and add traits. A concrete component combining a mixin with a non-mixin base must be
  prefixed by the non-mixin base (`MixinPrefixError`).
- Root names are unique per meta root (`ComponentNameDuplicatedError`).

Since names contain `_`, disable ruff's `N801` (or pep8-naming's equivalent) in projects
using morphtest. Abstract components are passed as `type[...]` on purpose, so also
disable mypy's `type-abstract` error code.

### One implementation per root

Within one depset, every root has exactly one concrete implementation. The only
exception is implementations in a subclass relation (parent + specialization),
of which only the most specific one ends up in the depset.

This rule is **how unrelated components get matched**. `Device.chip` and
`TestCase_NeedsChip.chip` are both `Dependency[Chip…]`, so they must resolve to the
*same* `Chip` implementation. `TestCase_NeedsChip` therefore only pairs with devices
that have `Chip_A`.

### Specialization (concrete parent → concrete subclass)

If a concrete component is selected and *all* dependencies of one of its concrete
subclasses are satisfied by the current selection, the subclass is selected
**instead**. This is automatic, not optional. Example: `TestCase_Any` →
`TestCase_Any_Big(TestCase_Any)` with `device: Dependency[Device_Big]` whenever the
device is a `Device_Big`.

Subclasses of an **abstract** component are *alternatives*: the solver picks one, and
each viable choice is a different solution.

### `if_not_overwritten(Default)`: default dependencies

```python
class Device(Component, abc.ABC):
    chip: Dependency[Chip] = if_not_overwritten(Chip_None)


class Device_Flexible(Device, abc.ABC):
    # default removed -> any Chip
    chip: Dependency[Chip]


class Device_Big(Device):
    # default replaced by a concrete requirement
    chip: Dependency[Chip_A]
```

- The field type is the dependency; the value is the implementation selected **if
  nothing else decides it**. In solver terms: if the component is selected and none of
  its subclasses is, the default is forced.
- Subclasses inherit the default until they **redeclare the field**. A redeclaration
  without `if_not_overwritten()` removes the default. With an abstract type it leaves the
  choice open, with a concrete type it pins it.
- Recommended convention: defaults are `_None`/`_No` implementations meaning "does not
  have this capability". With the one-implementation-per-root rule, a component that
  doesn't declare a capability can never be combined with one requiring it.
- Components that *support* a capability (work with or without it) declare the
  abstract type; components that *require* it declare the concrete type.

## Solver (`morphtest.solver`)

`ComponentSetSolver(entry, conditions=..., recommended_components=...)` uses an
incremental SAT solver (MiniSat via `python-sat` by default; `glucose4`, `cadical153`,
`cadical195` are also supported). Every generated clause is logged in readable form at
DEBUG level on logger `morphtest.solver`.

1. **Tree tracking**: starting from the entry component, it walks bases, subclasses and
   dependencies to discover all reachable components. Only components in **imported
   modules** exist, so the imports decide what is available.
2. **CNF clauses** (no auxiliary variables), one boolean variable per component (a
   selected subclass implies its bases):
   - entry component selected
   - abstract selected → at least one direct subclass selected
   - concrete selected → all its dependencies selected; and only selected if some
     selected component depends on it (the entry and its implementations always
     count as used)
   - root exclusivity: implementations of a root exclude each other unless in a
     subclass relation
   - defaults: concrete selected and none of its subclasses → its defaults selected
   - specialization: concrete selected and all deps of a subclass selected → subclass
     selected
   - conditions (below)
3. **Solving per group**: solutions are grouped by their combination of `AllOf`
   implementations, and one best fit is yielded per group. One solver is kept alive:
   1. find any solution; its `AllOf` implementations define the group
   2. with the group fixed, add each recommended component in order, as long as the
      formula stays satisfiable. `recommended_components` is a fixed list or a function
      getting the entry implementation of the group's first solution (`TestSuite`
      passes `TestCase.recommended_components` this way)
   3. enumerate the few remaining candidates and pick the one with the fewest
      components, then the smallest string (deterministic)
   4. exclude the whole group and repeat

The result is a `ComponentDependencySet` holding the most specific implementation per root.

### Conditions

- `X.all_of` (`AllOf`): **fan-out**. One depset for *every* implementation of `X` that
  can be part of a valid solution (more precisely, one per distinct combination of all
  `AllOf` implementations). Unsatisfiable implementations are silently skipped. A bare
  component (`TestSuite(Chip)`) means `.all_of`.
- `X.one_of` (`OneOf`): **filter only**. At least one implementation of `X` must be
  part of the solution, no fan-out.
- Both also require the implementation to be *used*, i.e. some selected component
  depends on it. The entry and its implementations always count as used.

Everything that is not an `AllOf` condition is **not** enumerated exhaustively; it
collapses to the best fit.

## Test suites (`morphtest.suite`)

```python
ts = TestSuite(Device)  # conditions of all leafs
ts(TestCase_Any)  # leaf: Device, TestCase_Any (all .all_of)
with ts(TestCase_NeedsChip):  # node: has children, no depsets of its own
    # leaf: Device, TestCase_NeedsChip, Chip_A.one_of
    ts(Chip_A.one_of, repeat=3)
```

- `TestSuite(*conditions)` has the entry `TestCase`, which is no condition itself: like
  every other component it resolves to the best fit, unless `TestCase` or a subclass
  is a condition (`TestSuite(TestCase, Device)` fans out over all test cases).
  `recommended_components` and `group_by` come from the class variables of each
  depset's `TestCase` implementation.
- `BaseTestSuite(entry, *conditions, recommended_components=..., group_by=...)` is the
  generic version with any entry component. The entry is also a condition (bare =
  `.all_of`); `recommended_components` and `group_by` are fixed lists or functions
  getting the entry implementation of a depset.
- Every `ts(...)` call adds a child; `with ts(...):` nests further calls under it. Each
  **leaf** is one condition set: the union of all conditions on its path, plus its
  `repeat`.
- Iterating the suite solves each leaf, sorts all depsets by `group_by` (in priority
  order, so consecutive depsets share expensive components) and yields each one
  `repeat` times.
- A leaf without solution raises `NoSolutionError` with `conditions`, `not_implemented`
  (condition components without any implementation) and `conflicting_conditions`
  (single conditions whose removal makes the leaf solvable).
- `TestSuite.run()` builds the `TestCase` of every depset and calls its `run()`.
  `BaseTestSuite` has no `run()`: iterate it and `build()` the depsets yourself.

## Components overview (`morphtest.overview`)

`save_components_overview(path, Component, entry_component=TestCase, source_url=..., toggles=...)`
writes an HTML page with the tree of all imported components below a meta root (roots,
implementations, specializations, dependencies, mixins). `source_url` maps a component
to a link (e.g. GitHub), `toggles` adds checkboxes that hide matching components.
