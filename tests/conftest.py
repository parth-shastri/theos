"""Shared fixtures. The scripted model every loop and agent test runs against."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from harness.testing import FakeModel
from harness.types import AssistantMessage


@pytest.fixture
def fake_model() -> Callable[..., FakeModel]:
    """Return a factory that builds a `FakeModel` from a script."""

    def build(script: Sequence[AssistantMessage | Exception], **kwargs) -> FakeModel:
        return FakeModel(script, **kwargs)

    return build
