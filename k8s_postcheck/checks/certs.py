"""Kubernetes 인증서 만료 체크.

두 가지 방법으로 인증서 만료를 확인합니다:

1. TLS 직접 연결 — kube-apiserver 인증서를 TLS 핸드셰이크로 확인.
   (kubeconfig 의 server URL 을 사용, 가장 확실)

2. kube-system Secret 스캔 — etcd, front-proxy, kubelet 등
   쿠버네티스가 관리하는 인증서 Secret 의 tls.crt 필드를 파싱.
   (Secret에 있는 것만 확인 가능)
"""

from __future__ import annotations

import ssl
import urllib.parse
from datetime import datetime, timezone

from kubernetes import client as k8s_client

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import timed

# 만료 경고 임계: 기본 30일 WARN, 7일 ERROR
DEFAULT_WARN_DAYS = 30
DEFAULT_ERROR_DAYS = 7


def _days_until(not_after: datetime) -> int:
    now = datetime.now(timezone.utc)
    if not_after.tzinfo is None:
        not_after = not_after.replace(tzinfo=timezone.utc)
    return max(0, (not_after - now).days)


def _check_tls_cert(host: str, port: int, timeout: float = 10.0) -> tuple[datetime | None, str]:
    """TLS 핸드셰이크로 서버 인증서 만료일을 가져옵니다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with ctx.wrap_socket(
            __import__("socket").create_connection((host, port), timeout=timeout),
            server_hostname=host,
        ) as sock:
            cert = sock.getpeercert()
            not_after_str = cert.get("notAfter", "")
            if not_after_str:
                not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                not_after = not_after.replace(tzinfo=timezone.utc)
                return not_after, ""
    except Exception as exc:
        return None, str(exc)
    return None, "인증서 정보 없음"


def _check_secret_certs(
    handle: K8sHandle,
    namespace: str,
    warn_days: int,
    error_days: int,
    result: CheckResult,
) -> None:
    """kube-system 의 TLS Secret 에서 인증서를 파싱합니다."""
    import base64

    try:
        secrets = handle.core.list_namespaced_secret(
            namespace=namespace,
            field_selector="type=kubernetes.io/tls",
        ).items
    except Exception as exc:
        result.findings.append(
            Finding(
                check="certs",
                severity=Severity.WARN,
                title=f"Secret 인증서 조회 실패 ({namespace})",
                detail=str(exc),
            )
        )
        return

    for secret in secrets:
        tls_crt = (secret.data or {}).get("tls.crt")
        if not tls_crt:
            continue
        try:
            pem = base64.b64decode(tls_crt)
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend
            cert = x509.load_pem_x509_certificate(pem, default_backend())
            not_after = cert.not_valid_after_utc
        except Exception:
            continue

        days = _days_until(not_after)
        name = secret.metadata.name or "?"
        sev = (
            Severity.ERROR if days <= error_days
            else Severity.WARN if days <= warn_days
            else Severity.INFO
        )
        if sev in (Severity.WARN, Severity.ERROR):
            result.findings.append(
                Finding(
                    check="certs",
                    severity=sev,
                    title=f"인증서 만료 임박: {name}",
                    detail=f"만료까지 {days}일 (만료일: {not_after.date()})",
                    resource=f"{namespace}/{name}",
                    suggestion=(
                        f"`kubeadm certs renew all` 또는 Kubespray 의 "
                        "`--tags certs` 로 인증서를 갱신하세요."
                    ),
                )
            )


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    warn_days: int = ctx.get("cert_warn_days", DEFAULT_WARN_DAYS)
    error_days: int = ctx.get("cert_error_days", DEFAULT_ERROR_DAYS)
    check_secrets: bool = ctx.get("cert_check_secrets", True)

    with timed("certs") as result:
        # kube-apiserver TLS 인증서 직접 확인
        try:
            cfg = handle.api_client.configuration
            server_url = cfg.host or ""
            parsed = urllib.parse.urlparse(server_url)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 6443)

            if host:
                not_after, err = _check_tls_cert(host, port)
                if err:
                    result.findings.append(
                        Finding(
                            check="certs",
                            severity=Severity.WARN,
                            title="kube-apiserver 인증서 조회 실패",
                            detail=err,
                            suggestion="TLS 연결 가능 여부와 방화벽 설정을 확인하세요.",
                        )
                    )
                elif not_after:
                    days = _days_until(not_after)
                    sev = (
                        Severity.ERROR if days <= error_days
                        else Severity.WARN if days <= warn_days
                        else Severity.INFO
                    )
                    result.findings.append(
                        Finding(
                            check="certs",
                            severity=sev,
                            title="kube-apiserver 인증서"
                            + (" 만료 임박!" if sev != Severity.INFO else " 정상"),
                            detail=f"만료까지 {days}일 (만료일: {not_after.date()})",
                            suggestion=(
                                "`kubeadm certs renew apiserver` 로 갱신하세요."
                                if sev != Severity.INFO else None
                            ),
                        )
                    )
        except Exception as exc:
            result.findings.append(
                Finding(
                    check="certs",
                    severity=Severity.WARN,
                    title="kube-apiserver TLS 체크 오류",
                    detail=str(exc),
                )
            )

        # Secret 기반 인증서 점검 (cryptography 라이브러리 있을 때만)
        if check_secrets:
            try:
                import cryptography  # noqa: F401
                _check_secret_certs(handle, "kube-system", warn_days, error_days, result)
            except ImportError:
                result.findings.append(
                    Finding(
                        check="certs",
                        severity=Severity.INFO,
                        title="Secret 인증서 상세 점검 건너뜀",
                        detail="`cryptography` 패키지 미설치. `pip install cryptography` 후 재실행.",
                    )
                )

    return result
