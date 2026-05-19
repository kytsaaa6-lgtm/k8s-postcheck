"""nodes 체크 유닛 테스트."""

from __future__ import annotations

from k8s_postcheck.checks.nodes import run
from k8s_postcheck.models import Severity
from tests.conftest import make_node


def test_all_ready(mock_handle):
    mock_handle.core.list_node.return_value.items = [
        make_node("node-1"),
        make_node("node-2"),
        make_node("node-3"),
    ]
    result = run(mock_handle, {"expected_nodes": 3})
    assert result.worst_severity in (Severity.OK, Severity.INFO)


def test_not_ready_node(mock_handle):
    mock_handle.core.list_node.return_value.items = [
        make_node("node-1", ready=False),
        make_node("node-2"),
    ]
    result = run(mock_handle, {})
    titles = [f.title for f in result.findings]
    assert any("NotReady" in t for t in titles)
    assert result.worst_severity == Severity.CRITICAL


def test_expected_node_mismatch(mock_handle):
    mock_handle.core.list_node.return_value.items = [make_node("node-1")]
    result = run(mock_handle, {"expected_nodes": 3})
    assert any("불일치" in f.title for f in result.findings)


def test_pressure_condition(mock_handle):
    mock_handle.core.list_node.return_value.items = [
        make_node("node-1", pressure=["MemoryPressure"]),
    ]
    result = run(mock_handle, {})
    assert any("압박" in f.title for f in result.findings)
    assert result.worst_severity == Severity.WARN


def test_version_mismatch(mock_handle):
    mock_handle.core.list_node.return_value.items = [
        make_node("node-1", version="v1.28.0"),
        make_node("node-2", version="v1.29.0"),
    ]
    result = run(mock_handle, {})
    assert any("버전 혼재" in f.title for f in result.findings)
