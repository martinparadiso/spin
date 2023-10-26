"""Core structure of machine creation"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Generic, Literal, Protocol, TypeVar

from spin.machine.machine import (
    CreatedMachine,
    DefinedMachine,
    Group,
    Machine,
    MachineUnderCreation,
)


class CommonStep:
    name: str
    """Friendly name to give the user"""

    description: None | str = None
    """Extended --user facing-- description about the step behaviour"""

    def __init__(self) -> None:
        self.rollbacks: list[Callable[[], Any]] = []
        """List of steps to execute when something fails.

        This callbacks are executed `in order`. So take special care when
        inserting callbacks that relay on another.

        The return value of the function is ignored.

        For instance, to delete some file and parent folder::

            some_file: pathlib.Path
            some_file.parent.mkdir()
            some_file.touch()
            self.rollbacks.append(some_file.unlink)
            self.rollbacks.append(some_file.parent.rmdir)
        """

        self.dry_run: bool = False
        """Set by the library. If set to ``True`` the step should not make modifications"""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    def rollback(self) -> None:
        """Reverse the modifications made by this step.

        Note: This default implementation traverses :py:attr:`rollbacks`, and
        executes all the callbacks in order. Can be overridden by the subclass
        to perform more complex tasks.
        """

        for rollback in self.rollbacks:
            rollback()


class ProcessableStep(CommonStep):
    """Common --default-- attributes and methods for all types of steps."""

    @abstractmethod
    def process(self):
        """Execute this step.

        Raises: If something fails.
        """
        raise NotImplementedError(f"{self.__class__.__name__}()")

    @classmethod
    def __original_accepts__(cls, machine: Any) -> bool:
        raise Exception("Internal error: calling non-set method")

    @classmethod
    def accepts(cls, machine: Any) -> bool:
        """Returns ``True`` if the step is applicable to the given machine"""
        raise Exception("Internal error: calling non-set method")


class DefinitionStep(ProcessableStep):
    """Steps to complete and validate the definition of a machine"""

    group: None | Group = None
    """Group where the machine should be stored."""

    def __init__(self, machine: Machine, tasks: list[CreationTask]) -> None:
        super().__init__()
        self.machine: Machine = machine
        self.tasks = tasks

    @classmethod
    @abstractmethod
    def accepts(cls, machine: Machine) -> bool:
        """Returns ``True`` if the step is applicable to the given machine.

        Args:
            machine: The machine to apply the step to.

        Returns:
            ``True`` if the step is valid for the machine. ``False`` if not.
        """
        raise NotImplementedError(f"{cls.__name__}")


class CreationTask:
    """Common base class for all creation tasks."""

    def __init__(self, machine: Machine | MachineUnderCreation) -> None:
        # HACK: Fix this typing error; we need to accept machine to insert
        #  tasks during definition
        self.machine: MachineUnderCreation = machine  # type: ignore
        """`Machine` the task belongs to."""


class StartTask:
    """Common base class for all start tasks."""

    def __init__(self, machine: Machine | CreatedMachine) -> None:
        # HACK: Fix this typing error; we need to accept machine to insert
        #  tasks during definition
        self.machine: MachineUnderCreation = machine  # type: ignore
        """`Machine` the task belongs to."""


_T = TypeVar("_T", contravariant=True)


class Solves(Protocol[_T]):
    @classmethod
    def confidence(cls, task: _T) -> int | Literal[False]:
        """Specify the *level* of confidence to fulfill the task on the given machine.

        If the task cannot be solved by this step, returns `False`.

        Args:
            task: The task to fulfill, contains the machine related
                to it.

        Return:
            The level of 'confidence'; used for tie-breaking. `0` means neutral, higher
            values mean 'more confidence', negative values are 'use if no other method
            is available'. `False` means the step cannot solve the given task.
        """
        ...

    def solve(self, task: _T) -> None:
        """Solve the task.

        Raises:
            Any exception the implementer considers approppiate.
        """
        ...


class CreationStep(CommonStep):
    """Steps to create a machine.

    TODO: PEP 646 defines variadic template arguments; but current
        support is limited. Once mypy fully supports it, CreationStep
        will be a variadic generic.
    """

    def __init__(self, machine: MachineUnderCreation) -> None:
        super().__init__()
        self.machine: MachineUnderCreation = machine

    @classmethod
    @abstractmethod
    def confidence(cls, task: CreationTask) -> int | Literal[False]:
        """Specify the *level* of confidence to fulfill the task on the given machine.

        If the task cannot be solved by this step, returns `False`.

        Args:
            task: The task to fulfill, contains the machine related
                to it.

        Return:
            The level of 'confidence'; used for tie-breaking. `0` means neutral, higher
            values mean 'more confidence', negative values are 'use if no other method
            is available'. `False` means the step cannot solve the given task.
        """
        ...

    @abstractmethod
    def solve(self, task: Any) -> None:
        """Solve the task.

        Raises:
            Any exception the implementer considers approppiate.
        """
        ...


class StartStep(ProcessableStep):
    """Base class for start steps

    Start steps are the sequence of actions performed over a machine
    object defined by the user in order to start it using a backend
    """

    print_console: bool = False
    """If set to ``True``, the guest console port is printed to stdout"""

    def __init__(self, machine: CreatedMachine) -> None:
        super().__init__()
        self.machine = machine
        """The current machine being process"""

    @classmethod
    @abstractmethod
    def accepts(cls, machine: CreatedMachine) -> bool:
        """Returns ``True`` if the step is applicable to the given machine.

        Args:
            machine: The machine to apply the step to.

        Returns:
            ``True`` if the step is valid for the machine. ``False`` if not.
        """
        raise NotImplementedError(f"{cls.__name__}")


class DestructionStep(ProcessableStep):
    """Base class for steps executed during machine destruction.

    Destruction means erasing all information about a machine.
    """

    def __init__(self, machine: CreatedMachine) -> None:
        super().__init__()
        self.machine: CreatedMachine = machine

    delete_storage: bool = False
    """If set to ``True``, the steps should destroy storage files."""

    @classmethod
    @abstractmethod
    def accepts(cls, machine: CreatedMachine) -> bool:
        """Returns ``True`` if the step is applicable to the given machine.

        Args:
            machine: The machine to apply the step to.

        Returns:
            ``True`` if the step is valid for the machine. ``False`` if not.
        """
        raise NotImplementedError(f"{cls.__name__}")
