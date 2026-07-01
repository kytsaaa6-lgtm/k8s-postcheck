"""etcd 체크 유닛 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from k8s_postcheck.checks.etcd import run
from k8s_postcheck.models import Severity


def _etcd_pod(name: str, ready: bool = True, phase: str = "Running") -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    pod.status.conditions = [cond]
    return pod


def _setup(handle, etcd_pods, cp_nodes, logs: str = ""):
    handle.core.list_namespaced_pod.return_value.items = etcd_pods
    handle.core.list_node.return_value.items = cp_nodes
    handle.core.read_namespaced_pod_log.return_value = logs


def test_no_etcd_pod_is_critical(mock_handle):
    _setup(mock_handle, [], [MagicMock()])
    result = run(mock_handle, {})
    assert any("etcd Pod 없음" in f.title for f in result.findings)
    assert result.worst_severity == Severity.CRITICAL


def test_healthy_three_members(mock_handle):
    pods = [_etcd_pod(f"etcd-cp{i}") for i in range(3)]
    nodes = [MagicMock() for _ in range(3)]
    _setup(mock_handle, pods, nodes)
    result = run(mock_handle, {})
    assert result.worst_severity in (Severity.OK, Severity.INFO)


def test_even_member_count_warns(mock_handle):
    pods = [_etcd_pod("etcd-cp0"), _etcd_pod("etcd-cp1")]
    nodes = [MagicMock(), MagicMock()]
    _setup(mock_handle, pods, nodes)
    result = run(mock_handle, {})
    assert any("짝수" in f.title for f in result.findings)
    assert result.worst_severity == Severity.WARN


def test_member_count_mismatch_is_error(mock_handle):
    pods = [_etcd_pod("etcd-cp0")]
    nodes = [MagicMock() for _ in range(3)]  # 3 control-plane, 1 etcd
    _setup(mock_handle, pods, nodes)
    result = run(mock_handle, {})
    assert any("멤버 수 불일치" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_unhealthy_etcd_pod_is_critical(mock_handle):
    pods = [
        _etcd_pod("etcd-cp0"),
        _etcd_pod("etcd-cp1", ready=False, phase="Error"),
        _etcd_pod("etcd-cp2"),
    ]
    nodes = [MagicMock() for _ in range(3)]
    _setup(mock_handle, pods, nodes)
    result = run(mock_handle, {})
    assert result.worst_severity == Severity.CRITICAL
    assert any("etcd Pod 비정상" in f.title for f in result.findings)


def test_log_error_pattern_warns(mock_handle):
    pods = [_etcd_pod(f"etcd-cp{i}") for i in range(3)]
    nodes = [MagicMock() for _ in range(3)]
    _setup(mock_handle, pods, nodes, logs="etcdserver: failed to send out heartbeat on time")
    result = run(mock_handle, {})
    assert any("로그 이상 패턴" in f.title for f in result.findings)
