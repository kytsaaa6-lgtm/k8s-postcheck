"""certs 체크 유닛 테스트.

`cryptography` 는 필수 의존성이 아니므로, Secret 인증서 파싱 경로는 라이브러리
유무에 관계없이 안전하게 동작해야 한다. 여기서는 외부 TLS 연결/파싱 없이도
검증 가능한 순수 로직과 방어 코드를 고정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from k8s_postcheck.checks.certs import _check_secret_certs, _days_until, run
from k8s_postcheck.models import CheckResult, Severity


def test_days_until_future_and_past():
    future = datetime.now(timezone.utc) + timedelta(days=10)
    past = datetime.now(timezone.utc) - timedelta(days=5)
    assert _days_until(future) in (9, 10)
    assert _days_until(past) == 0  # 음수는 0 으로 클램프


def test_days_until_naive_datetime_is_treated_as_utc():
    naive = (datetime.now(timezone.utc) + timedelta(days=3)).replace(tzinfo=None)
    assert _days_until(naive) in (2, 3)


def test_secret_listing_failure_warns():
    handle = MagicMock()
    handle.core.list_namespaced_secret.side_effect = RuntimeError("forbidden")
    result = CheckResult(name="certs")
    _check_secret_certs(handle, "kube-system", 30, 7, result)
    assert any("Secret 인증서 조회 실패" in f.title for f in result.findings)
    assert result.worst_severity == Severity.WARN


def test_secret_without_tls_crt_is_skipped():
    handle = MagicMock()
    secret = MagicMock()
    secret.data = {}  # tls.crt 없음
    secret.metadata.name = "empty"
    handle.core.list_namespaced_secret.return_value.items = [secret]
    result = CheckResult(name="certs")
    _check_secret_certs(handle, "kube-system", 30, 7, result)
    assert result.findings == []


def test_run_without_host_and_without_secret_scan_is_clean(mock_handle):
    # host 를 비워 TLS 직접 연결을 건너뛰고, Secret 스캔도 끈다.
    mock_handle.api_client.configuration.host = ""
    result = run(mock_handle, {"cert_check_secrets": False})
    # 예외 없이 동작해야 하며 ERROR/CRITICAL 은 없어야 한다.
    assert result.error is None
    assert result.worst_severity in (Severity.OK, Severity.INFO, Severity.WARN)
