from __future__ import annotations

import ast
from pathlib import Path

import pytest

import evcf.forecasting.r11_s0_models as models
from evcf.forecasting.r11_s0_contracts import PARAMETER_BAND


def test_torch_is_not_imported_at_module_import_time():
    tree = ast.parse(Path(models.__file__).read_text())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert "torch" not in imports
    assert "torch.nn" not in imports


def test_all_frozen_model_families_have_valid_shapes_and_parameter_band():
    torch = pytest.importorskip("torch")
    batch = 4
    history = torch.zeros(batch, 96, 2, dtype=torch.float32)
    issue_context = torch.zeros(batch, 5, dtype=torch.float32)
    target_context = torch.zeros(batch, 5, 6, dtype=torch.float32)
    for name in ("GRU", "TCN", "NHiTS", "PatchTST"):
        model = models.make_model(name)
        output = model(history, issue_context, target_context)
        assert output.shape == (batch, 5)
        count = models.trainable_parameter_count(model)
        assert PARAMETER_BAND[0] <= count <= PARAMETER_BAND[1], (name, count)


def test_unknown_model_family_fails_closed():
    with pytest.raises(Exception, match="UNKNOWN_MODEL_FAMILY"):
        models.make_model("Mamba")
