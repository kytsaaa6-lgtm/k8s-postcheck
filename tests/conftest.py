"""공통 테스트 픽스처."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from k8s_postcheck.auth import K8sHandle
from k8s_postcheck.models import Severity


@pytest.fixture()
def mock_handle() -> K8sHandle:
    """Kubernetes API 를 mock 한 K8sHandle 픽스처."""
    handle = K8sHandle(
        api_client=MagicMock(),
        core=MagicMock(),
        apps=MagicMock(),
        custom=MagicMock(),
        cluster_label="test-cluster",
    )
    return handle


def make_node(name: str, ready: bool = True, pressure: list[str] | None = None, version: str = "v1.29.0"):
    """테스트용 Node 객체 생성 헬퍼."""
    from unittest.mock import MagicMock
    node = MagicMock()
    node.metadata.name = name

    conditions = []
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True" if ready else "False"
    conditions.append(ready_cond)

    for cond_type in (pressure or []):
        c = MagicMock()
        c.type = cond_type
        c.status = "True"
        conditions.append(c)

    node.status.conditions = conditions
    node.status.node_info.kubelet_version = version
    return node


def make_pod(name: str, phase: str = "Running", ready: bool = True, namespace: str = "kube-system"):
    """테스트용 Pod 객체 생성 헬퍼."""
    from unittest.mock import MagicMock
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.metadata.labels = {}
    pod.status.phase = phase
    pod.status.container_statuses = []

    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = "True" if ready else "False"
    pod.status.conditions = [ready_cond]
    return pod
