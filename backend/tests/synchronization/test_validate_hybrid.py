import pytest

from synchronization import validate_hybrid


@pytest.mark.parametrize(
    ("source", "normalize_many"),
    [
        ("bbva", False),
        ("buepp", True),
    ],
)
def test_create_hybrid_runner(source, normalize_many):
    runner = validate_hybrid.create_runner(source)

    assert runner.source == source
    assert runner.storage_mode == "hybrid"
    assert runner.normalize_many is normalize_many
    assert runner.allow_deactivation is False


@pytest.mark.parametrize("source", ["bbva", "buepp"])
def test_main_runs_validation_only(monkeypatch, source):
    calls = []

    class FakeRunner:
        def run(self, validate_only=False):
            calls.append(validate_only)

    def fake_create_runner(requested_source):
        assert requested_source == source
        return FakeRunner()

    monkeypatch.setattr(
        validate_hybrid,
        "create_runner",
        fake_create_runner,
    )

    validate_hybrid.main(["--source", source])

    assert calls == [True]


def test_rejects_unsupported_source():
    with pytest.raises(ValueError, match="no soportada"):
        validate_hybrid.create_runner("banco_del_sol")


def test_cli_rejects_unsupported_source():
    with pytest.raises(SystemExit) as error:
        validate_hybrid.main(
            ["--source", "banco_del_sol"]
        )

    assert error.value.code == 2