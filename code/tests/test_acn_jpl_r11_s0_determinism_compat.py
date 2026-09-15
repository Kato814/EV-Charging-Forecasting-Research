from __future__ import annotations

import numpy as np
import pytest

from evcf.forecasting import acn_jpl_r11_s0_determinism_compat as compat
from evcf.forecasting import acn_jpl_r11_s0_models as models


def test_deterministic_linear_interpolate_matches_pytorch_cpu_geometry():
    torch = pytest.importorskip("torch")
    source = torch.arange(2 * 3 * 6, dtype=torch.float32).reshape(2, 3, 6)
    expected = torch.nn.functional.interpolate(
        source,
        size=17,
        mode="linear",
        align_corners=False,
    )
    actual = compat.deterministic_linear_interpolate(torch, source, 17)
    assert torch.allclose(actual, expected, atol=1e-6, rtol=1e-6)


def test_deterministic_nhits_preserves_frozen_parameter_count_and_shape():
    torch = pytest.importorskip("torch")
    compat.install_deterministic_nhits_compat()
    model = models.make_deep_model(torch, "nhits")
    assert models.count_trainable_parameters(model) == 116133
    history = torch.zeros((2, 96, 2), dtype=torch.float32)
    issue = torch.zeros((2, 5), dtype=torch.float32)
    target = torch.zeros((2, 5, 6), dtype=torch.float32)
    output = model(history, issue, target)
    assert output.shape == (2, 5)
    assert np.isfinite(output.detach().numpy()).all()
