from unittest.mock import patch

import pytest

import spin.utils.dependency
from spin.utils.dependency import DependencyManager


class TestDependency:
    def test_dep_not_satisfies(self) -> None:
        """Must raise exception if a required dep. does not satisfy cond."""

        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as instance:
            instance.return_value = depman

            @spin.utils.dependency.dep
            class A:
                value = False

            @spin.utils.dependency.dep(requires=A)
            class B:
                value = True

            @spin.utils.dependency.dep(requires=B)
            class C:
                value = True

            with pytest.raises(Exception) as exce_info:
                depman.fullgraph(cond=lambda n: n.value, instance_of=object)

            exce_info.match(f"{A} required by {B} not available")

    def test_dep_forward_def(self) -> None:
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as instance:
            instance.return_value = depman

            @spin.utils.dependency.dep(before="C")
            class A:
                pass

            @spin.utils.dependency.dep(before=A)
            class B:
                pass

            @spin.utils.dependency.dep
            class C:
                pass

            ret = depman.fullgraph(cond=lambda _: True, instance_of=object)

            assert ret == [B, A, C]


class TestClassDecorator:
    def test_basic(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep
            class NoDependencies:
                pass

            assert NoDependencies in depman.known_deps
            assert len(depman.relations) == 0

    def test_simple(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep()
            class A:
                pass

            @spin.utils.dependency.dep(requires=A)
            class B:
                pass

            print(depman.known_deps)
            assert len(depman.known_deps) == 2
            assert len(depman.relations) == 1
            assert (B, A) in depman.relations

    def test_str(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep(requires="SOME_DEP")
            class A:
                pass

            @spin.utils.dependency.dep(provides="SOME_DEP")
            class B:
                pass

            assert len(depman.known_deps) == 2
            assert len(depman.relations) == 1
            assert (A, "SOME_DEP") in depman.relations

    def test_multiple(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep
            class A:
                pass

            @spin.utils.dependency.dep(requires={A, "A_DEP"})
            class B:
                pass

            @spin.utils.dependency.dep(provides="A_DEP")
            class Prov:
                pass

            assert len(depman.known_deps) == 3
            assert len(depman.relations) == 2


class TestDecoratorResolve:
    def test_simple(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep
            class A:
                pass

            @spin.utils.dependency.dep(requires=A)
            class B:
                pass

            resolv = depman.fullgraph(cond=lambda _: True, instance_of=object)

            assert resolv == [A, B]

    # def test_replacement(self):
    #     depman = DependencyManager()
    #
    #     with patch("spin.utils.dependency.DependencyManager.instance") as dm:
    #         dm.return_value = depman
    #
    #         @spin.utils.dependency.dep(requires="SOME_DEP")
    #         class A:
    #             pass
    #
    #         @spin.utils.dependency.dep(provides="SOME_DEP")
    #         class B:
    #             pass
    #
    #         @spin.utils.dependency.dep(provides="SOME_DEP")
    #         class C:
    #             pass
    #
    #         resolv = depman.reach(A)
    #         assert resolv == [B, A] or resolv == [C, A]

    def test_unmet_deps(self):
        depman = DependencyManager()

        with patch("spin.utils.dependency.DependencyManager.instance") as dm:
            dm.return_value = depman

            @spin.utils.dependency.dep(requires="NON_EXISTENT")
            class A:
                pass

            with pytest.raises(Exception) as excinfo:
                depman.fullgraph(cond=lambda _: True, instance_of=object)

            excinfo.match(".*[Nn]o provider for.*")
