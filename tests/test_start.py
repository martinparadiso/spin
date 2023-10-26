"""Test the start process"""

from __future__ import annotations

from typing import Literal
from unittest.mock import Mock

from spin.machine.machine import CreatedMachine
from spin.machine.steps import Solves, StartStep, StartTask
from spin.utils.dependency import RegisterPool


def test_step_generation() -> None:
    register = RegisterPool()

    class TaskX(StartTask):
        pass

    @register.start_step(requires=[TaskX])
    class StartStepA(StartStep):
        def process(self):
            pass

        @classmethod
        def accepts(cls, machine: CreatedMachine) -> bool:
            return True

    @register.start_step(before=[TaskX])
    class StartStepB(StartStep):
        def process(self):
            pass

        @classmethod
        def accepts(cls, machine: CreatedMachine) -> bool:
            return True

    @register.start_step(solves=[TaskX])
    class SolveX(StartStep, Solves[TaskX]):
        @classmethod
        def confidence(cls, task: TaskX) -> int | Literal[False]:
            return 10

        def solve(self, task: TaskX) -> None:
            return

    task = TaskX(Mock())
    order, tasks = register.start_pipeline(
        [task], lambda x, y: list(x)[0], lambda s: True
    )
    assert order == [StartStepB, SolveX, StartStepA]
    assert tasks == {SolveX: [task]}
