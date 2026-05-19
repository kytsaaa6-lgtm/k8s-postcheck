"""클러스터 후처리 진단 체크 모듈 레지스트리."""

from __future__ import annotations

from collections.abc import Callable

from ..auth import K8sHandle
from ..models import CheckResult
from . import certs, etcd, helm_releases, nodes, system_pods, velero

CheckFunc = Callable[[K8sHandle, dict], CheckResult]

REGISTRY: dict[str, CheckFunc] = {
    "nodes": nodes.run,
    "system_pods": system_pods.run,
    "helm_releases": helm_releases.run,
    "certs": certs.run,
    "velero": velero.run,
    "etcd": etcd.run,
}


def available_checks() -> list[str]:
    return list(REGISTRY.keys())
