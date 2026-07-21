from replayguard.cli import main


def test_init_and_inspect(tmp_path, capsys):
    root = tmp_path / ".verify"
    assert main(["--store", str(root), "init"]) == 0
    assert main(["--store", str(root), "inspect"]) == 0
    assert "[]" in capsys.readouterr().out


def test_redact_check(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("sk-abcdefghijklmnop")
    assert main(["redact-check", str(path)]) == 1


def test_suite_cli_workflow(tmp_path, capsys):
    from replayguard.schema import Run
    from replayguard.storage import LocalStore
    root, suite_path = tmp_path / "store", tmp_path / "suite.json"
    store = LocalStore(root)
    run = Run("cli-case", status="ok")
    store.save_run(run)
    assert main(["--store", str(root), "suite", "create", str(suite_path), "--name", "cli-suite"]) == 0
    assert main(["--store", str(root), "suite", "add", str(suite_path), run.id]) == 0
    assert main(["--store", str(root), "suite", "run", str(suite_path)]) == 0
    assert '"passed": 1' in capsys.readouterr().out
