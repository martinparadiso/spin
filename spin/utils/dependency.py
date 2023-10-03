"""Dependency related functionality"""

from __future__ import annotations

import dataclasses
import warnings
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)

from typing_extensions import TypeGuard

from spin.machine.steps import BaseTask, CreationStep

Dependencies = Optional[Union[type, str, Set[Union[type, str]]]]
"""Supported values when defining a class-based dependency graph.

A dependency can be:

    - ``None``, indicating there are no required dependencies, or the element
      provides nothing beyond itself.
    - ``type``, indicating a requires ``class`` (or ``type``) requires by the
      element. For instance a *ResizeDisk* functionality would require an
      existing *DiskFile* to resize.
    - ``str`` provides a language-independant way of defining dependencies. I.
      e. to avoid depending explicitly on a class, a generic term can be
      defined in a string. For instance, if there are two classes providing the
      main disk for a virtual machine, say *DownloadDisk* and *MakeDisk*, each
      one can use ``provides='MAIN_DISK'``, and the rest of the classes depend
      on ``'MAIN_DISK'`` instead of *DownloadDisk* or *MakeDisk*.
    - ``Set[type | str]`` provides a mechanism to define multiple dependencies.
"""


def _is_reference_to(cls: Any, class_name: str) -> bool:
    """Return ``True`` if the *partial* ``class_name`` *can* be a forward
    reference to the class ``cls``. For instance:

    >>> _is_reference_to(str, 'builtins.str')
    True

    >>> _is_reference_to(str, 'str')
    True

    >>> _is_reference_to(third_party.str, 'str')
    True

    >>> _is_reference_to(thirdparty.str, 'builtins.str')
    False
    """
    fullpath = cls.__module__.split(".") + cls.__qualname__.split(".")
    to_check = class_name.split(".")

    for cls_level, to_check_level in zip(fullpath[::-1], to_check[::-1]):
        if cls_level != to_check_level:
            return False
    return True


T = TypeVar("T")


def resolve_soft_dependencies(
    providers: dict[str, Type[T]],
    soft_dependencies: set[tuple[str | Type[T], Type[T]]],
    known_deps: set[Type[T]],
) -> Set[Tuple[Type[T], Type[T]]]:
    """Return the list of soft-dependencies.

    The function resolves all 'forward references' and generics
    found.

    Returns:
        A set containing all the soft dependencies; where each
        element is a tuple in the shape of ``(Element, SoftRequirement)``.

    TODO: Implement conflict resolution; and replace tokens (currently only
          types are supported).
    """
    soft_deps: Set[Tuple[Type[T], Type[T]]] = set()

    for type_, soft_requirement in soft_dependencies:
        if isinstance(type_, str):
            as_str = type_
            compatible_clss = list(
                filter(
                    lambda dep: _is_reference_to(dep, as_str),
                    known_deps,
                )
            )
            if len(compatible_clss) == 0:
                if type_ in providers:
                    type_ = providers[type_]
                else:
                    raise ValueError(f"Unknown dependency: {type_}")

            elif len(compatible_clss) == 1:
                type_ = compatible_clss[0]
            else:
                raise ValueError(f"Found multiple matches for dependency: {type_}")
        soft_deps.add((type_, soft_requirement))
        continue

    return soft_deps


def resolve_providers(
    tokens: Set[str],
    providers: dict[str, list[T]],
) -> Dict[str, T]:
    """Find classes capable of providing all the generics in *tokens*

    Args:
        tokens: Set of strings used as *tokens* during the definition of
            steps; which need to be replaced by actual classes providing
            said token.
        constraint: A Callable which receives a class T and returns ``True``
            if the class is an acceptable provider. This normally means
            verifying the class corresponds to the current global action
            (for instance, veryfing it is a CreationStep during the creation
            of a machine).

    Returns:
        A ``dict``; where each key is a token, and the corresponding value
        a type ``T`` providing said token.
    """
    ret: Dict[str, T] = {}
    for token in tokens:
        if token not in providers:
            raise ValueError(f"No provider for {token} dependency")
        available = providers.get(token, [])
        if len(available) == 0:
            raise ValueError(f"No provider for {token} dependency")
        if len(available) > 1:
            warnings.warn(f"More than one provider for {token}: {available}")
        ret[token] = available[0]
    return ret


class DependencyManager:
    """Singleton storing the dependencies specified by @dep"""

    _instance: DependencyManager

    def __init__(self) -> None:
        self.known_deps: Set[type] = set()
        self.relations: Set[Tuple[type, type | str]] = set()
        self.soft_dependencies: Set[Tuple[str | type, type]] = set()
        self.providers: Dict[str, List[type]] = {}

    @classmethod
    def instance(cls) -> DependencyManager:
        """Retrieve the only instance of this singleton

        Returns:
            The DependencyManager
        """
        if getattr(cls, "_instance", None) is None:
            cls._instance = DependencyManager()
        return cls._instance

    def reset(self) -> None:
        """Reset the object, remove all registered dependencies"""
        self.known_deps = set()
        self.relations = set()
        self.providers = {}

    def fullgraph(
        self,
        *,
        cond: Callable[[Any], bool],
        instance_of: Type[T],
    ) -> list[Type[T]]:
        """Return a dependency list with all the nodes that satisfy ``cond``.

        This function takes all the known dependencies, filters out all that
        don't satisfy ``cond`` and are sub-classes of ``instance_of``, and generates
        a traversal sequence for the resulting dependency graph.

        Args:
            cond: A callable with signature ``f(node: Any) -> bool``, which
                returns ``True`` if the node must be included in the graph,
                or ``False`` if must be excluded.
            instance_of: The graph is constructed only with classes derived from
                ``instance_of``.

        Raises:
            ValueError: If both ``cond`` and ``instance_of`` are given.

        Returns:
            An ordered ``list``, containing all the dependencies that satisfy
            ``cond``. The list is a *safe* traversal of the dependency graph.
        """

        def check_type(e: type) -> TypeGuard[Type[T]]:
            return issubclass(e, instance_of)

        visited: set[Type[T]] = set()

        nodes: set[Type[T]] = {d for d in self.known_deps if check_type(d) and cond(d)}
        providers_to_search = {
            k: [vv for vv in v if issubclass(vv, instance_of) and cond(vv)]
            for k, v in self.providers.items()
        }
        providers = resolve_providers(
            set(
                req
                for (node, req) in self.relations
                if (node in nodes and isinstance(req, str))
            ),
            providers_to_search,
        )
        # FirstElement requires SecondElement
        relations: Set[Tuple[Type[T], Type[T]]] = set()
        for t, r in self.relations:
            if isinstance(r, str):
                continue
            if not issubclass(t, instance_of) or not issubclass(r, instance_of):
                continue
            relations.add((t, r))

        for node, requirement in self.relations:
            if not issubclass(node, instance_of):
                continue
            if node in nodes and isinstance(requirement, str):
                if requirement not in providers:
                    raise ValueError(
                        f"No provider for generic dependency {requirement} required by {node}"
                    )
                relations.add((node, providers[requirement]))
        # Insert soft-requirements.
        index = 0
        soft_deps = [
            *resolve_soft_dependencies(
                providers,
                self.soft_dependencies,
                self.known_deps,
            )
        ]
        while index < len(soft_deps):
            soft_dep = soft_deps[index]
            node = soft_dep[0]
            node_before = soft_dep[1]
            if (
                node in nodes
                and cond(node_before)
                and check_type(node_before)
                and soft_dep not in relations
            ):
                relations.add(soft_dep)
                index = 0
            index += 1

        ret: list[Type[T]] = []

        def start_from(node: Type[T]) -> None:
            node_requires = {rd for k, rd in relations if k == node}
            visited.add(node)
            for requirement in node_requires:
                if requirement not in nodes:
                    raise Exception(f"{requirement} required by {node} not available")
                if requirement not in visited:
                    start_from(requirement)
            ret.append(node)

        while len(visited) != len(nodes):
            # Pick a node, any, and traverse
            start_from((nodes - visited).pop())

        return ret


@overload
def dep(c: Type[T]) -> Type[T]:
    ...


@overload
def dep(
    c=None,
    *,
    requires: Dependencies = None,
    provides: Dependencies = None,
    before: Dependencies = None,
) -> Callable[[Type[T]], Type[T]]:
    ...


# HACK: T must be a subclass of B, and all the dependencies and requirements
# must *also* be derived from such class B. For instance, all DefinitionStep
# must have DefinitionStep requirements
def dep(
    c: Optional[Type[T]] = None,
    *,
    requires: Dependencies = None,
    provides: Dependencies = None,
    before: Dependencies = None,
) -> Type[T] | Callable[[Type[T]], Type[T]]:
    """Insert this class into the dependency graph.

    Args:
        requires: Set of :py:attr:`Dependencies` the annotated class requires
            before performing certain action.
        provides: Set of :py:attr:`Dependencies` the annotated class provides
            to other classes.
        before: Set of *reverse dependencies*. Useful for inserting steps in the
            middle.

    Examples:

        Define a class A, and then a class B which depends on A. An empty
        ``@dep`` adds said class to the pool of known dependencies::

            @dep
            class A: pass

            @dep(requires=A) # Or @dep(requires={A})
            class B: pass

        Define a class which provides a generic term --in the form of a
        ``str``--, and then another class depending on it::

            @dep(provides="AGNOSTIC_DEPENDENCY")
            class C: pass

            # In another file, not importing C:
            @dep(requires="AGNOSTIC_DEPENDENCY")
            class D: pass
    """

    def decorator_dep(class_: Type[T]) -> Type[T]:
        dm = DependencyManager.instance()
        dm.known_deps.add(class_)

        nonlocal requires
        nonlocal provides
        nonlocal before

        if requires is not None:
            if isinstance(requires, str) or not isinstance(requires, Iterable):
                requires = {requires}
            for req in requires:
                dm.relations.add((class_, req))

        if before is not None:
            if isinstance(before, str) or not isinstance(before, Iterable):
                before = {before}
            for rev_dep in before:
                dm.soft_dependencies.add((rev_dep, class_))

        if provides is not None:
            if isinstance(provides, str) or not isinstance(provides, Iterable):
                provides = {provides}
            for prov in provides:
                if isinstance(prov, str):
                    if prov not in dm.providers:
                        dm.providers[prov] = []
                    dm.providers[prov].append(class_)

        return class_

    if c is None:
        return decorator_dep
    return decorator_dep(c)


_BT = BaseTask
_CS = CreationStep


class RegisterPool:
    @dataclasses.dataclass
    class _CreationStep:
        requires: list[Type[_BT] | Type[_CS]] = dataclasses.field(default_factory=list)
        after: list[Type[_BT] | Type[_CS]] = dataclasses.field(default_factory=list)
        provides: list[Type[_BT]] = dataclasses.field(default_factory=list)
        before: list[Type[_BT] | Type[_CS]] = dataclasses.field(default_factory=list)

    def __init__(self) -> None:
        self.creation_steps: dict[Type[CreationStep], RegisterPool._CreationStep] = {}

    def solves(self, *tasks: Type[BaseTask]):
        """Register a Creation Step.

        Args:
            provides: Collection of  `Tasks` this step resolves.
        """
        assert len(tasks) > 0
        _T = TypeVar("_T", bound=CreationStep)

        def _register_inner(step: Type[_T]) -> Type[_T]:
            """Register a creation step"""
            self.creation_steps[step].provides = list(tasks)
            return step

        return _register_inner

    def register(
        self,
        *,
        requires: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
        after: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
        before: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
    ):
        """Register a Creation Step.

        Args:
            requires: Collection of `CreationStep` and/or `Tasks` required
                by this step. The process will be executed once all
                the requirements have been executed.
            after: Collection of `CreationStep` and/or `Tasks` to execute
                *before* this step; it they were to be executed at all.
                Essentially defines a 'soft' dependency; where the step
                does not fail if the steps and tasks are not present in
                the final creation procedure.
            provides: Collection of  `Tasks` this step resolves.
            before: Collection of `CreationStep` and/or `Tasks` to execute
                after this step. Useful for inserting the step in the middle
                of an existing pipeline.
        """
        requires = requires or []
        after = after or []
        before = before or []
        _T = TypeVar("_T", bound=CreationStep)

        def _register_inner(step: Type[_T]) -> Type[_T]:
            """Register a creation step"""
            self.creation_steps[step] = RegisterPool._CreationStep(
                list(requires), list(after), [], list(before)
            )
            return step

        return _register_inner

    class _HelpRet(NamedTuple):
        requirements: dict[Type[CreationStep], list[Type[CreationStep]]]
        task_assignment: dict[Type[CreationStep], list[BaseTask]]

    def _creation_graph(
        self,
        tasks: Collection[BaseTask],
        select: Callable[
            [Collection[Type[CreationStep]], BaseTask], Type[CreationStep]
        ],
    ) -> _HelpRet:
        # FIXME: We are not 'cascading' task dependencies:
        # If task A requires task B, but task B is not explicitly added
        # as a dependency, it is never added; and the resolution fails.
        # Furthermore, it fails in the wrong place, when we call as_step
        # it tries to find the step solving B.

        all_providers_for_each_task: dict[BaseTask, list[Type[CreationStep]]] = {
            task: [] for task in tasks
        }
        for task in tasks:
            for step, provides in map(
                lambda s: (s[0], s[1].provides), self.creation_steps.items()
            ):
                if type(task) in provides:
                    all_providers_for_each_task[task].append(step)

        def select_provider(provs, task_t) -> Type[CreationStep]:
            provs = [prov for prov in provs if prov.confidence(task_t) is not False]
            if len(provs) == 0:
                raise ValueError(f"No provider for task {task_t}")
            return select(provs, task_t)

        providers = {
            task: select_provider(provs, task)
            for task, provs in all_providers_for_each_task.items()
        }

        def as_step(__t: Type[BaseTask] | Type[CreationStep]) -> Type[CreationStep]:
            if issubclass(__t, BaseTask):
                if __t not in {type(task) for task in providers}:
                    # TODO: Store the dependencies so we can properly notify
                    # the user about who's requesting __t.
                    raise ValueError(f"Task {__t}  has no provider")
                # NOTE: Here we need to supply the provider for the task
                # *type* __t, but we are working with concrete objects, so
                # we are going to pick the first ocurreance of such class
                for task, provider in providers.items():
                    if isinstance(task, __t):
                        return provider
                raise ValueError(f"Task {__t}  has no provider")
            return __t

        nodes = {*providers.values()}
        steps = {
            step: data for step, data in self.creation_steps.items() if step in nodes
        }

        relations = set(
            (a, as_step(c))
            for (a, b) in map(lambda s: (s[0], s[1].requires), steps.items())
            for c in b
        )

        _soft_deps = {
            (n, as_step(requirement))
            for n, softdep in steps.items()
            for requirement in softdep.after
        }.union(
            {
                (as_step(requirement), n)
                for n, softdep in steps.items()
                for requirement in softdep.before
            }
        )
        relations.update((node, req) for (node, req) in _soft_deps if req in nodes)

        d: dict[Type[CreationStep], list[Type[CreationStep]]] = {n: [] for n in nodes}
        for node, requires in relations:
            d[node].append(requires)

        provides_: dict[Type[CreationStep], list[BaseTask]] = {
            step_type: [] for step_type in d
        }
        for task, provided_by in providers.items():
            provides_[provided_by].append(task)
        return RegisterPool._HelpRet(d, provides_)

    def creation_pipeline(
        self,
        tasks: Collection[BaseTask],
        select: Callable[
            [Collection[Type[CreationStep]], BaseTask], Type[CreationStep]
        ],
    ) -> tuple[list[Type[CreationStep]], dict[Type[CreationStep], list[BaseTask]]]:
        """Generate the sequence of steps to create a Machine.

        Args:
            tasks: Extra tasks to add to the requirements.
            condition: A callable which accepts any CreationStep, and
                returns `True` if the step is should be used.
            select: Function used to find the most capable task.
        """

        relations, task_resolvers = self._creation_graph(tasks, select)
        nodes = set(relations.keys())
        visited: set[Type[CreationStep]] = set()
        ret: list[Type[CreationStep]] = []

        def start_from(node: Type[CreationStep]) -> None:
            node_requires = relations[node]
            visited.add(node)
            for requirement in node_requires:
                if requirement not in nodes:
                    raise ValueError(f"{requirement} required by {node} not available")
                if requirement not in visited:
                    start_from(requirement)
            ret.append(node)

        while visited < nodes:
            start_from((nodes - visited).pop())

        return ret, task_resolvers


pool = RegisterPool()
register = pool.register
solves = pool.solves


dependencies = DependencyManager.instance()
"""The DependencyManager *singleton*"""
