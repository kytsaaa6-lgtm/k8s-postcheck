"""velero 체크 유닛 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from k8s_postcheck.checks import velero
from k8s_postcheck.checks.velero import run
from k8s_postcheck.models import Severity


def _velero_pod(name: str = "velero-0", ready: bool = True, phase: str = "Running") -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    pod.status.conditions = [cond]
    return pod


def _bsl(name: str, phase: str, message: str = "") -> dict:
    return {"metadata": {"name": name}, "status": {"phase": phase, "message": message}}


def _setup(handle, pods, bsls):
    handle.core.list_namespaced_pod.return_value.items = pods
    handle.custom.list_namespaced_custom_object.return_value = {"items": bsls}


def test_healthy_velero_and_bsl(mock_handle):
    _setup(mock_handle, [_velero_pod()], [_bsl("default", "Available")])
    result = run(mock_handle, {})
    assert result.worst_severity in (Severity.OK, Severity.INFO)


def test_no_velero_pod_is_error(mock_handle):
    _setup(mock_handle, [], [])
    result = run(mock_handle, {})
    assert any("Velero Pod 없음" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_bsl_unavailable_is_error(mock_handle):
    _setup(mock_handle, [_velero_pod()], [_bsl("default", "Unavailable", "connection refused")])
    result = run(mock_handle, {})
    assert any("BackupStorageLocation 비정상" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_no_bsl_warns(mock_handle):
    _setup(mock_handle, [_velero_pod()], [])
    result = run(mock_handle, {})
    assert any("BackupStorageLocation 없음" in f.title for f in result.findings)


def test_unhealthy_velero_pod_is_error(mock_handle):
    _setup(mock_handle, [_velero_pod(ready=False, phase="CrashLoopBackOff")], [_bsl("d", "Available")])
    result = run(mock_handle, {})
    assert any("Velero Pod 비정상" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_minio_health_failure_is_error(mock_handle, monkeypatch):
    _setup(mock_handle, [_velero_pod()], [_bsl("default", "Available")])
    monkeypatch.setattr(velero, "_check_minio", lambda url, timeout=10.0: (False, "conn refused"))
    result = run(mock_handle, {"minio_url": "http://minio.test:9000"})
    assert any("MinIO health 실패" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_minio_health_ok(mock_handle, monkeypatch):
    _setup(mock_handle, [_velero_pod()], [_bsl("default", "Available")])
    monkeypatch.setattr(velero, "_check_minio", lambda url, timeout=10.0: (True, "HTTP 200"))
    result = run(mock_handle, {"minio_url": "http://minio.test:9000"})
    assert any("MinIO health 정상" in f.title for f in result.findings)
    assert result.worst_severity in (Severity.OK, Severity.INFO)
