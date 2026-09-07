"""Tests for the pytest plugin, run through pytester (pytest inside pytest).

The inner runs never pass "-p testsniper.plugin". The plugin has to arrive
through its pytest11 entry point, so a broken entry point fails here rather
than being papered over by an explicit load.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import GIT_ENV_ARGS

from testsniper import plan as plan_mod
from testsniper.nodes import FileNodes
from testsniper.plan import Plan

MIXED_TEST_FILE = """
import pytest

from pkg.changed import build
from pkg.quiet import quiet


@pytest.fixture
def client():
    return build()


def test_uses_the_change():
    assert build() == 1


@pytest.mark.parametrize("n", [1, 2, 3])
def test_parametrized_on_the_change(n):
    assert build() == 1 and n


def test_uses_the_fixture(client):
    assert client == 1


def test_untouched():
    assert quiet() == 2


class TestGroup:
    def test_in_a_class(self):
        assert quiet() == 2
"""

PKG = {
    "pkg/__init__.py": "",
    "pkg/changed.py": "def build():\n    return 1\n",
    "pkg/quiet.py": "def quiet():\n    return 2\n",
}


def _make_project(pytester: pytest.Pytester) -> None:
    for rel, content in PKG.items():
        path = pytester.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (pytester.path / "conftest.py").write_text("", encoding="utf-8")
    (pytester.path / "tests").mkdir(exist_ok=True)
    (pytester.path / "tests" / "test_mixed.py").write_text(MIXED_TEST_FILE, encoding="utf-8")
    (pytester.path / "tests" / "test_elsewhere.py").write_text(
        "def test_far_away():\n    assert True\n", encoding="utf-8"
    )


def _write_plan(pytester: pytest.Pytester, plan: Plan) -> Path:
    path = pytester.path / "plan.json"
    plan_mod.write(path, plan)
    return path


def _narrowed_plan(pytester: pytest.Pytester, selected: set[tuple[str, str]]) -> Plan:
    known = {
        ("", "test_uses_the_change"),
        ("", "test_parametrized_on_the_change"),
        ("", "test_uses_the_fixture"),
        ("", "test_untouched"),
        ("TestGroup", "test_in_a_class"),
    }
    return Plan(
        root=str(pytester.path.resolve()),
        files={
            "tests/test_mixed.py": FileNodes(
                relpath="tests/test_mixed.py",
                narrowed=True,
                reason="narrowed by name usage",
                selected=selected,
                known=known,
            )
        },
        indexed={"tests/test_mixed.py", "tests/test_elsewhere.py"},
        summary="1 changed file(s)",
    )


def test_plugin_is_inert_without_any_flag(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    result = pytester.runpytest()
    result.assert_outcomes(passed=8)
    out = result.stdout.str()
    # Registered (pytest lists it) but silent: no header, no summary section.
    assert "plugins: testsniper" in out
    assert "testsniper:" not in out
    assert "selected 8 of" not in out


def test_plan_narrows_within_a_file(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    path = _write_plan(
        pytester,
        _narrowed_plan(pytester, {("", "test_uses_the_change"), ("", "test_uses_the_fixture")}),
    )
    result = pytester.runpytest(f"--testsniper-plan={path}")
    result.assert_outcomes(passed=2, deselected=6)
    result.stdout.fnmatch_lines(["*tests/test_mixed.py: 2 of 7, narrowed by name usage*"])


def test_selecting_a_function_keeps_all_of_its_parametrized_cases(
    pytester: pytest.Pytester,
) -> None:
    _make_project(pytester)
    path = _write_plan(
        pytester, _narrowed_plan(pytester, {("", "test_parametrized_on_the_change")})
    )
    result = pytester.runpytest(f"--testsniper-plan={path}", "-v")
    result.assert_outcomes(passed=3, deselected=5)
    assert "test_parametrized_on_the_change[2]" in result.stdout.str()


def test_a_class_method_is_selected_by_its_class_path(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    path = _write_plan(pytester, _narrowed_plan(pytester, {("TestGroup", "test_in_a_class")}))
    result = pytester.runpytest(f"--testsniper-plan={path}", "-v")
    result.assert_outcomes(passed=1, deselected=7)
    assert "TestGroup::test_in_a_class" in result.stdout.str()


def test_a_file_absent_from_the_plan_is_fully_deselected(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    plan = _narrowed_plan(pytester, {("", "test_untouched")})
    path = _write_plan(pytester, plan)
    result = pytester.runpytest(f"--testsniper-plan={path}")
    # test_elsewhere.py is indexed but not in files, so its test is dropped.
    result.assert_outcomes(passed=1, deselected=7)


def test_a_test_in_an_unindexed_file_is_never_dropped(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    plan = _narrowed_plan(pytester, set())
    plan.indexed = {"tests/test_mixed.py"}
    path = _write_plan(pytester, plan)
    result = pytester.runpytest(f"--testsniper-plan={path}")
    result.assert_outcomes(passed=1, deselected=7)
    result.stdout.fnmatch_lines(["*1 test(s) in files testsniper did not index*"])


def test_an_unknown_item_in_a_narrowed_file_is_kept(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    plan = _narrowed_plan(pytester, set())
    # Pretend the analysis never saw the class method: it must survive.
    nodes = plan.files["tests/test_mixed.py"]
    nodes.known = {k for k in nodes.known if k[0] != "TestGroup"}
    path = _write_plan(pytester, plan)
    result = pytester.runpytest(f"--testsniper-plan={path}", "-v")
    result.assert_outcomes(passed=1, deselected=7)
    assert "TestGroup::test_in_a_class" in result.stdout.str()


def test_select_all_plan_runs_everything(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    plan = Plan(root=str(pytester.path.resolve()), select_all=True, indexed=set())
    path = _write_plan(pytester, plan)
    result = pytester.runpytest(f"--testsniper-plan={path}")
    result.assert_outcomes(passed=8)
    # select_all is not "nothing was indexed"; it must not say so.
    assert "did not index" not in result.stdout.str()
    result.stdout.fnmatch_lines(["*selected 8 of 8 collected tests*"])


def test_summary_reports_confidence_and_reasons(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    plan = _narrowed_plan(pytester, {("", "test_uses_the_change")})
    plan.confidence = "Medium"
    plan.confidence_reasons = ["star imports in 1 file(s) can hide dependencies"]
    path = _write_plan(pytester, plan)
    result = pytester.runpytest(f"--testsniper-plan={path}")
    result.stdout.fnmatch_lines(
        [
            "*selection confidence: Medium*",
            "*- star imports in 1 file(s) can hide dependencies*",
        ]
    )


def test_a_malformed_plan_is_a_clean_usage_error(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    path = pytester.path / "plan.json"
    path.write_text("{not json", encoding="utf-8")
    result = pytester.runpytest(f"--testsniper-plan={path}")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "testsniper: plan is not valid JSON" in result.stderr.str()
    assert "Traceback" not in result.stderr.str()


def test_plan_and_analysis_flags_cannot_be_combined(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    path = _write_plan(pytester, _narrowed_plan(pytester, set()))
    result = pytester.runpytest(f"--testsniper-plan={path}", "--testsniper")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "cannot be combined" in result.stderr.str()


def test_running_outside_a_git_repo_is_a_clean_usage_error(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    result = pytester.runpytest("--testsniper")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "testsniper:" in result.stderr.str()
    assert "Traceback" not in result.stderr.str()


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", *GIT_ENV_ARGS, "commit", "-q", "-m", "init"], cwd=root, check=True)


def test_testsniper_flag_analyzes_the_working_tree(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    _git_init(pytester.path)
    (pytester.path / "pkg" / "changed.py").write_text(
        "def build():\n    return 1\n\n\ndef extra():\n    return 3\n", encoding="utf-8"
    )
    result = pytester.runpytest("--testsniper")
    # The three tests that reach pkg.changed, with the parametrized one
    # expanding to three cases, and nothing from test_elsewhere.py.
    result.assert_outcomes(passed=5, deselected=3)
    result.stdout.fnmatch_lines(
        [
            "*testsniper: default mode, working tree vs HEAD*",
            "*selected 5 of 8 collected tests*",
            "*selection confidence: High*",
        ]
    )


def test_no_changes_deselects_everything(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    _git_init(pytester.path)
    result = pytester.runpytest("--testsniper")
    result.assert_outcomes(deselected=8)
    result.stdout.fnmatch_lines(["*no changes detected*"])


def test_aggressive_mode_is_honoured(pytester: pytest.Pytester) -> None:
    _make_project(pytester)
    _git_init(pytester.path)
    (pytester.path / "pkg" / "changed.py").write_text(
        "def build():\n    return 1\n\n\ndef extra():\n    return 3\n", encoding="utf-8"
    )
    result = pytester.runpytest("--testsniper", "--testsniper-mode=aggressive")
    result.assert_outcomes(passed=5, deselected=3)
    result.stdout.fnmatch_lines(["*aggressive mode, working tree vs HEAD*"])


def test_the_entry_point_registers_the_plugin_in_a_subprocess(
    pytester: pytest.Pytester,
) -> None:
    """No -p flag anywhere: only the pytest11 entry point can supply --testsniper-plan."""
    _make_project(pytester)
    path = _write_plan(pytester, _narrowed_plan(pytester, {("", "test_uses_the_change")}))
    result = pytester.runpytest_subprocess(f"--testsniper-plan={path}")
    result.assert_outcomes(passed=1, deselected=7)
    result.stdout.fnmatch_lines(["*plugins:*testsniper*"])


CONFTEST_PROJECT = {
    "tests/conftest.py": (
        "import pytest\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def beta():\n"
        "    return 2\n"
    ),
    "tests/test_alpha.py": "def test_with_alpha(alpha):\n    assert alpha == 1\n",
    "tests/test_beta.py": "def test_with_beta(beta):\n    assert beta == 2\n",
}

# Same fixtures, same behavior, but alpha's body is different parsed syntax.
CONFTEST_ALPHA_EDITED = CONFTEST_PROJECT["tests/conftest.py"].replace(
    "def alpha():\n    return 1\n", "def alpha():\n    value = 1\n    return value\n"
)


def test_a_changed_conftest_is_read_through_its_diff_by_the_plugin(
    pytester: pytest.Pytester,
) -> None:
    """The plugin analyzes with the same revision the command does.

    Without a way to read the conftest's previous content the analysis falls
    back to running its whole subtree, which is the answer for a caller that
    has no revision, not the answer for one running inside a git repository.
    """
    for rel, content in CONFTEST_PROJECT.items():
        path = pytester.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git_init(pytester.path)
    (pytester.path / "tests" / "conftest.py").write_text(CONFTEST_ALPHA_EDITED, encoding="utf-8")
    result = pytester.runpytest("--testsniper")
    result.assert_outcomes(passed=1, deselected=1)
    result.stdout.fnmatch_lines(["*selected 1 of 2 collected tests*"])
