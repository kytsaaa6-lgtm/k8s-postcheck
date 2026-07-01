"""system_pods 체크 유닛 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from k8s_postcheck.checks.system_pods import _labels_match, run
from k8s_postcheck.models import Severity


def _pod(name: str, labels: dict, ready: bool = True, phase: str = "Running") -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = "kube-system"
    pod.metadata.labels = labels
    pod.status.phase = phase
    pod.status.container_statuses = []
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    pod.status.conditions = [cond]
    return pod


def _set_pods(handle, pods):
    handle.core.list_namespaced_pod.return_value.items = pods


def test_labels_match_equality_and_inequality():
    assert _labels_match({"k8s-app": "kube-dns"}, "k8s-app=kube-dns") is True
    assert _labels_match({"k8s-app": "other"}, "k8s-app=kube-dns") is False
    assert _labels_match({"k8s-app": "cilium"}, "k8s-app!=kube-dns") is True
    assert _labels_match({"k8s-app": "kube-dns"}, "k8s-app!=kube-dns") is False


def test_all_components_healthy(mock_handle):
    _set_pods(
        mock_handle,
        [
            _pod("coredns-1", {"k8s-app": "kube-dns"}),
            _pod("metrics-server-1", {"k8s-app": "metrics-server"}),
        ],
    )
    result = run(mock_handle, {})
    # 모든 컴포넌트 존재 + Ready → WARN/ERROR 없음
    assert result.worst_severity in (Severity.OK, Severity.INFO)


def test_missing_required_component(mock_handle):
    # coredns 만 있고 metrics-server 없음
    _set_pods(mock_handle, [_pod("coredns-1", {"k8s-app": "kube-dns"})])
    result = run(mock_handle, {})
    assert any("컴포넌트 Pod 없음: metrics-server" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_skip_component_suppresses_missing(mock_handle):
    _set_pods(mock_handle, [_pod("coredns-1", {"k8s-app": "kube-dns"})])
    result = run(mock_handle, {"skip_components": ["metrics-server"]})
    assert not any("metrics-server" in f.title for f in result.findings)


def test_unhealthy_component_pod_is_error(mock_handle):
    _set_pods(
        mock_handle,
        [
            _pod("coredns-1", {"k8s-app": "kube-dns"}, ready=False, phase="CrashLoopBackOff"),
            _pod("metrics-server-1", {"k8s-app": "metrics-server"}),
        ],
    )
    result = run(mock_handle, {})
    assert result.worst_severity == Severity.ERROR
    assert any(f.severity == Severity.ERROR and "coredns" in (f.resource or "") for f in result.findings)


def test_extra_required_component(mock_handle):
    _set_pods(
        mock_handle,
        [
            _pod("coredns-1", {"k8s-app": "kube-dns"}),
            _pod("metrics-server-1", {"k8s-app": "metrics-server"}),
        ],
    )
    # cilium 을 required 로 넣었지만 pod 가 없음 → ERROR
    result = run(mock_handle, {"required_components": {"cilium": "k8s-app=cilium"}})
    assert any("cilium" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR
