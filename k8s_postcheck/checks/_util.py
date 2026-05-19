"""체크 모듈 공통 헬퍼."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from ..models import CheckResult, Finding, Severity


@contextmanager
def timed(name: str) -> Iterator[CheckResult]:
    """체크를 타이밍하고 예외를 ERROR Finding 으로 변환합니다."""
    result = CheckResult(name=name)
    start = time.perf_counter()
    try:
        yield result
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        result.findings.append(
            Finding(
                check=name,
                severity=Severity.ERROR,
                title=f"{name} 점검 중 예외 발생",
                detail=str(exc),
                suggestion="kubeconfig 권한, API server 접근성, CRD 설치 여부를 확인하세요.",
            )
        )
    finally:
        result.duration_ms = int((time.perf_counter() - start) * 1000)


def pod_is_ready(pod) -> bool:
    """Pod 의 Ready condition 이 True 인지 확인합니다."""
    conditions = (pod.status.conditions or []) if pod.status else []
    for c in conditions:
        if c.type == "Ready":
            return c.status == "True"
    return False


def pod_phase_ok(pod) -> bool:
    phase = (pod.status.phase or "").lower() if pod.status else ""
    return phase in {"running", "succeeded"}
