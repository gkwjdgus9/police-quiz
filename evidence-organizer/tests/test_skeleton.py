"""패키지 골격이 import 되는지 확인한다."""

import importlib

import pytest

MODULES = [
    "eo",
    "eo.schema",
    "eo.hashing",
    "eo.extract",
    "eo.timeline",
    "eo.ledger",
    "eo.report",
    "eo.evaluate",
    "eo.parsers",
    "eo.parsers.kakao",
    "eo.parsers.bank_csv",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
