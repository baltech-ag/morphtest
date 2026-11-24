from pathlib import Path

from typer.testing import CliRunner

from morphtest.cli import app, condition_completions

SUITE = str(Path(__file__).parent / "cli_suite.py")

runner = CliRunner()


class TestRun:
    def test_runs_test_suite_of_conditions(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "TestCase_Cli_A", "CliDevice"])

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "[1/2] TestCase_Cli_A[CliDevice=CliDevice_Big]",
            "TestCase_Cli_A on CliDevice_Big",
            "[2/2] TestCase_Cli_A[CliDevice=CliDevice_Small]",
            "TestCase_Cli_A on CliDevice_Small",
            "2 tests passed",
        ]

    def test_one_of_runs_best_fit(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "TestCase_Cli.one_of"])

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "[1/1] TestCase_Cli_A[CliDevice=CliDevice_Big]",
            "TestCase_Cli_A on CliDevice_Big",
            "1 test passed",
        ]

    def test_failing_test_case_stops_with_exit_code_1(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "TestCase_CliFailing"])

        assert result.exit_code == 1
        assert isinstance(result.exception, AssertionError)
        assert "passed" not in result.stdout

    def test_unknown_component_suggests_close_matches(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "CliDevic"])

        assert result.exit_code == 2
        assert "unknown component CliDevic (did you mean: CliDevice" in result.stderr

    def test_unknown_suffix(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "CliDevice.any_of"])

        assert result.exit_code == 2
        assert "unknown suffix .any_of" in result.stderr

    def test_no_solution_shows_diagnosis(self) -> None:
        result = runner.invoke(app, ["run", SUITE, "CliDevice_Big", "CliDevice_Small"])

        assert result.exit_code == 2
        assert "no solution found" in result.stderr
        assert "remove any of these conditions" in result.stderr

    def test_unknown_module(self) -> None:
        result = runner.invoke(app, ["run", "not_existing_module"])

        assert result.exit_code == 2
        assert "cannot import not_existing_module" in result.stderr


class TestDescribe:
    def test_shows_conditions_tests_and_components(self) -> None:
        result = runner.invoke(app, ["describe", SUITE])

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            "# CONDITIONS",
            "CliDevice.all_of, TestCase_Cli.all_of, TestCase_Cli_A.all_of (repeat=1)",
            "CliDevice.all_of, TestCase_Cli.all_of, TestCase_Cli_B.all_of (repeat=2)",
            "",
            "# TESTS",
            "TestCase_Cli_A[CliDevice=CliDevice_Big]",
            "TestCase_Cli_B[CliDevice=CliDevice_Big]",
            "TestCase_Cli_B[CliDevice=CliDevice_Big]",
            "TestCase_Cli_A[CliDevice=CliDevice_Small]",
            "TestCase_Cli_B[CliDevice=CliDevice_Small]",
            "TestCase_Cli_B[CliDevice=CliDevice_Small]",
            "",
            "# COMPONENTS",
            "CliDevice: 6",
            "CliDevice_Big: 3",
            "CliDevice_Small: 3",
            "TestCase: 6",
            "TestCase_Cli: 6",
            "TestCase_Cli_A: 2",
            "TestCase_Cli_B: 4",
            "------",
            "6 tests in this test suite",
        ]

    def test_target_without_ts(self) -> None:
        result = runner.invoke(app, ["describe", "morphtest.component"])

        assert result.exit_code == 2
        assert "morphtest.component defines no test suite `ts`" in result.stderr


class TestOverview:
    def test_writes_components_with_local_source_links(self, tmp_path: Path) -> None:
        output = tmp_path / "overview.html"
        result = runner.invoke(app, ["overview", SUITE, "-o", str(output)])

        assert result.exit_code == 0, result.output
        content = output.read_text(encoding="utf-8")
        for component in ("TestCase", "TestCase_Cli_A", "CliDevice", "CliDevice_Big"):
            assert f'id="{component}"' in content
        assert f'href="{Path(SUITE).resolve().as_uri()}#L' in content

    def test_source_url_template(self, tmp_path: Path) -> None:
        output = tmp_path / "overview.html"
        result = runner.invoke(
            app,
            [
                "overview",
                SUITE,
                "-o",
                str(output),
                "--source-url",
                "https://example.com/{path}#L{line}",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "cli_suite.py#L" in output.read_text(encoding="utf-8")


def test_completes_conditions_of_target() -> None:
    assert condition_completions(SUITE, "CliDevice_B") == [
        "CliDevice_Big",
        "CliDevice_Big.all_of",
        "CliDevice_Big.one_of",
    ]
