from types import SimpleNamespace

import pytest

from synchronization.hybrid_baseline import (
    compare_baselines,
    write_baseline,
)


def make_promotions(*ids):
    return [
        SimpleNamespace(source_id=source_id)
        for source_id in ids
    ]


def test_baseline_detects_new_promotions(tmp_path):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"

    write_baseline(
        previous,
        "bbva",
        make_promotions("100", "200"),
    )

    write_baseline(
        current,
        "bbva",
        make_promotions("100", "200", "300"),
    )

    result = compare_baselines(
        "bbva",
        current,
        previous,
    )

    assert result["new"] == ["300"]
    assert result["missing"] == []
    assert result["unchanged"] == ["100", "200"]


def test_baseline_blocks_missing_promotions(tmp_path):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"

    write_baseline(
        previous,
        "bbva",
        make_promotions("100", "200", "300"),
    )

    write_baseline(
        current,
        "bbva",
        make_promotions("100", "300", "400"),
    )

    with pytest.raises(
        RuntimeError,
        match="desaparecidas",
    ):
        compare_baselines(
            "bbva",
            current,
            previous,
        )


def test_first_baseline_requires_approval(tmp_path):
    current = tmp_path / "current.json"

    write_baseline(
        current,
        "buepp",
        make_promotions("100"),
    )

    with pytest.raises(
        RuntimeError,
        match="autorización explícita",
    ):
        compare_baselines(
            "buepp",
            current,
        )

    result = compare_baselines(
        "buepp",
        current,
        allow_initial=True,
    )

    assert result["new"] == ["100"]


def test_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicados"):
        write_baseline(
            tmp_path / "baseline.json",
            "bbva",
            make_promotions("100", "100"),
        )