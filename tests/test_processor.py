"""Test the machine processor: start, creation and destruction
of machines"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import spin.machine.processor


@patch("spin.machine.processor.pool")
@patch("spin.machine.processor.is_under_creation", new=lambda _: True)
@patch("spin.machine.processor.isinstance")
def test_solve_call(isinstance_mock: Mock, pool_mock: MagicMock) -> None:
    machine_mock = MagicMock(name="machine_mock")
    step_class = MagicMock(name="step_class")
    non_solver_class = MagicMock(name="non_solver_class")
    task_class = MagicMock(name="task_class")

    def patched_isinstance(obj, expected):
        if expected is task_class:
            return obj is task_class.return_value
        return False

    isinstance_mock.side_effect = patched_isinstance

    pool_mock.creation_pipeline.return_value = [non_solver_class, step_class], {
        step_class: [task_class.return_value]
    }

    under_testing = spin.machine.processor.MachineProcessor(machine_mock)
    under_testing.save_to_disk = Mock()
    under_testing._persistent_storage = Mock()
    under_testing._generate_tasks = Mock(return_value=[task_class.return_value])
    under_testing.create()

    step_class.assert_called_once_with(machine_mock)
    step_class.return_value.solve.assert_called_once_with(task_class.return_value)
    non_solver_class.return_value.solve.assert_not_called()

    under_testing.save_to_disk.assert_called_once()
    machine_mock.backend.update.assert_called_once()
