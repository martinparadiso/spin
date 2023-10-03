"""Actions requested by the user to execute at a later time."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, List, NewType, Union, overload

if TYPE_CHECKING:
    from spin.machine.machine import Machine

Seconds = Union[int, float]


class Action:
    """Base class for inputs"""

    Serialized = NewType("Serialized", dict)
    SerializedSequence = List[Serialized]

    def to_dict(self) -> Action.Serialized:
        """Convert the action into a dictionary

        Returns:
            A :py:class:`dict`, for later reconstruction of the action with
            :py:func:`from_dict`.
        """
        raise NotImplementedError()

    @classmethod
    def from_dict(cls, data: dict) -> Action:
        """Construct an action from a dict

        Raises:
            ValueError: If no Action can be constructed from with the
                data provided.

        Returns:
            An Action object, constructed from the given dictionary.
        """
        raise NotImplementedError()

    @overload
    @classmethod
    def deserialize(cls, data: SerializedSequence) -> list[Action]:
        ...

    @overload
    @classmethod
    def deserialize(cls, data: Action.Serialized) -> Action:
        ...

    @classmethod
    def deserialize(
        cls, data: SerializedSequence | Action.Serialized
    ) -> list[Action] | Action:
        """Construct a list of actions from a list of dicts

        Args:
            data: A dict or a list of dicts, generated with :py:func:`to_dict`.
                if you pass a single dictionary, a single element will be
                returned.

        Returns:
            A list of Actions
        """
        actions = Action.__subclasses__()
        sequence: list[Action] = []
        if not isinstance(data, list):
            data = [data]
        for elem in data:
            action = None
            for actionclass in actions:
                try:
                    action = actionclass.from_dict(elem)
                    sequence.append(action)
                except ValueError:
                    pass
            if action is None:
                raise ValueError(f"Unknown action: {elem}")
        if len(data) == 1:
            return sequence[0]
        return sequence

    @abstractmethod
    def execute(self, machine: "Machine") -> bool:
        """Execute this action on a machine.

        Args:
            machine: The target machine, where the action is performed.

        Returns:
            ``True`` if the action was successful, ``False`` if not.

        Raises:
            Whatever the sub-class/implementation raises.
        """
