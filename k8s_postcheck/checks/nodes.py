"""노드 준비 상태 체크.

- 모든 노드 Ready 여부
- 노드 압박 조건 (MemoryPressure / DiskPressure / PIDPressure)
- 기대 노드 수 대비 실제 노드 수
- Kubelet 버전 일관성 (마스터/워커 간 major.minor 불일치)
"""

from __future__ import annotations

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import timed

# Ready=False 인 노드를 ERROR, 압박 조건 노드는 WARN
_PRESSURE_CONDITIONS = {"MemoryPressure", "DiskPressure", "PIDPressure"}


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    expected_nodes: int | None = ctx.get("expected_nodes")

    with timed("nodes") as result:
        nodes = handle.core.list_node().items

        result.findings.append(
            Finding(
                check="nodes",
                severity=Severity.INFO,
                title="노드 수집",
                detail=f"전체 {len(nodes)}개",
            )
        )

        if expected_nodes is not None and len(nodes) != expected_nodes:
            sev = Severity.ERROR if len(nodes) < expected_nodes else Severity.WARN
            result.findings.append(
                Finding(
                    check="nodes",
                    severity=sev,
                    title="노드 수 불일치",
                    detail=f"기대 {expected_nodes}개 / 실제 {len(nodes)}개",
                    suggestion=(
                        "kubespray 가 모든 노드를 등록했는지, "
                        "누락된 노드의 kubelet 상태를 확인하세요."
                    ),
                )
            )

        not_ready: list[str] = []
        pressured: dict[str, list[str]] = {}
        versions: list[str] = []

        for node in nodes:
            name = node.metadata.name or "?"
            conditions = (node.status.conditions or []) if node.status else []
            version = (node.status.node_info.kubelet_version or "") if node.status and node.status.node_info else ""
            if version:
                versions.append(version)

            ready = False
            for cond in conditions:
                if cond.type == "Ready":
                    ready = cond.status == "True"
                elif cond.type in _PRESSURE_CONDITIONS and cond.status == "True":
                    pressured.setdefault(name, []).append(cond.type)

            if not ready:
                not_ready.append(name)

        for name in not_ready:
            result.findings.append(
                Finding(
                    check="nodes",
                    severity=Severity.CRITICAL,
                    title=f"노드 NotReady: {name}",
                    detail="Ready condition = False",
                    resource=name,
                    suggestion=(
                        f"`kubectl describe node {name}` 에서 conditions 와 "
                        "events 를 확인하세요. kubelet 재시작 또는 네트워크 플러그인(CNI) "
                        "문제일 가능성이 높습니다."
                    ),
                )
            )

        for name, conds in pressured.items():
            result.findings.append(
                Finding(
                    check="nodes",
                    severity=Severity.WARN,
                    title=f"노드 자원 압박: {name}",
                    detail=f"압박 조건: {', '.join(conds)}",
                    resource=name,
                    suggestion=(
                        "MemoryPressure → 불필요한 Pod eviction 발생 가능. "
                        "DiskPressure → kubelet imagefs/rootfs 사용률 확인. "
                        "PIDPressure → `ulimit -u` 또는 systemd DefaultTasksMax 확인."
                    ),
                )
            )

        # kubelet 버전 일관성
        minor_versions = set()
        for v in versions:
            parts = v.lstrip("v").split(".")
            if len(parts) >= 2:
                minor_versions.add(f"{parts[0]}.{parts[1]}")
        if len(minor_versions) > 1:
            result.findings.append(
                Finding(
                    check="nodes",
                    severity=Severity.WARN,
                    title="kubelet 버전 혼재",
                    detail=f"minor 버전 집합: {sorted(minor_versions)}",
                    suggestion=(
                        "kubespray 가 모든 노드를 동일 버전으로 업그레이드했는지 확인하세요. "
                        "버전 차이가 크면 API 호환성 문제가 발생할 수 있습니다."
                    ),
                )
            )

    return result
