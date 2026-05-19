"""콘솔 / JSON / Markdown 리포트 렌더러."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .models import SEVERITY_ORDER, PostCheckReport, Severity

_SEV_COLOR = {
    Severity.OK: "green",
    Severity.INFO: "cyan",
    Severity.WARN: "yellow",
    Severity.ERROR: "red",
    Severity.CRITICAL: "bold red",
}

_SEV_ICON = {
    Severity.OK: "✓",
    Severity.INFO: "ℹ",
    Severity.WARN: "⚠",
    Severity.ERROR: "✗",
    Severity.CRITICAL: "✗✗",
}


def to_console(report: PostCheckReport, console: Console) -> None:
    console.rule(f"[bold]k8s-postcheck — {report.cluster}[/bold]")

    tbl = Table(show_header=True, header_style="bold", box=None)
    tbl.add_column("체크", style="bold", min_width=20)
    tbl.add_column("상태", min_width=10)
    tbl.add_column("소요(ms)", justify="right")

    for r in report.results:
        sev = r.worst_severity
        color = _SEV_COLOR[sev]
        icon = _SEV_ICON[sev]
        tbl.add_row(r.name, f"[{color}]{icon} {sev.value.upper()}[/{color}]", str(r.duration_ms))
    console.print(tbl)

    for r in report.results:
        notable = [
            f for f in r.findings
            if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[Severity.WARN]
        ]
        if not notable:
            continue
        console.print(f"\n[bold]{r.name}[/bold]")
        for f in notable:
            color = _SEV_COLOR[f.severity]
            console.print(f"  [{color}]{_SEV_ICON[f.severity]} {f.title}[/{color}]")
            if f.detail:
                console.print(f"    {f.detail}")
            if f.suggestion:
                console.print(f"    [dim]→ {f.suggestion}[/dim]")

    sev = report.worst_severity
    color = _SEV_COLOR[sev]
    duration = ""
    if report.finished_at:
        elapsed = (report.finished_at - report.started_at).total_seconds()
        duration = f"  ({elapsed:.1f}s)"
    console.rule(
        f"[{color}]전체 결과: {_SEV_ICON[sev]} {sev.value.upper()}[/{color}]{duration}"
    )


def to_json(report: PostCheckReport, path: Path) -> None:
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def to_markdown(report: PostCheckReport, path: Path) -> None:
    lines: list[str] = []
    lines.append(f"# k8s-postcheck Report — `{report.cluster}`\n")
    if report.finished_at:
        lines.append(f"**실행 시각**: {report.started_at.isoformat()}")
        elapsed = (report.finished_at - report.started_at).total_seconds()
        lines.append(f"  **소요**: {elapsed:.1f}s\n")
    lines.append(f"**전체 결과**: `{report.worst_severity.value.upper()}`\n")

    lines.append("## 요약\n")
    lines.append("| 체크 | 결과 | 소요(ms) |")
    lines.append("|---|---|---|")
    for r in report.results:
        icon = _SEV_ICON[r.worst_severity]
        lines.append(f"| {r.name} | {icon} {r.worst_severity.value.upper()} | {r.duration_ms} |")

    lines.append("\n## 상세\n")
    for r in report.results:
        notable = [
            f for f in r.findings
            if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER[Severity.WARN]
        ]
        if not notable:
            continue
        lines.append(f"### {r.name}\n")
        for f in notable:
            icon = _SEV_ICON[f.severity]
            lines.append(f"**{icon} {f.title}**")
            if f.detail:
                lines.append(f"\n{f.detail}")
            if f.suggestion:
                lines.append(f"\n> {f.suggestion}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
