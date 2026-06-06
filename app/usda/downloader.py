from __future__ import annotations

import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin


DATA_TYPE_MARKERS = {
    "Foundation Foods": ("foundation", "foundation foods", "foundation-foods"),
    "SR Legacy": ("sr legacy", "srlegacy", "sr_legacy", "sr-legacy"),
    "FNDDS": ("fndds", "survey foods"),
    "Branded": ("branded", "branded foods", "branded-foods"),
}


@dataclass(frozen=True)
class DownloadCandidate:
    data_type: str
    url: str
    label: str


@dataclass(frozen=True)
class DownloadResult:
    extracted_path: Path
    downloads: list[DownloadCandidate]


class _DownloadPageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.text = ""
        self._current_href: str | None = None
        self._current_label: list[str] = []
        self.anchors: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._current_href = urljoin(self.base_url, href)
            self._current_label = []

    def handle_data(self, data: str) -> None:
        self.text += data
        if self._current_href:
            self._current_label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        label = " ".join(part.strip() for part in self._current_label if part.strip())
        context = self.text[-500:]
        self.anchors.append((self._current_href, label, context))
        self._current_href = None
        self._current_label = []


def discover_usda_json_downloads(page_html: str, page_url: str) -> list[DownloadCandidate]:
    parser = _DownloadPageParser(page_url)
    parser.feed(page_html)
    candidates: list[DownloadCandidate] = []
    seen: set[str] = set()

    for href, label, context in parser.anchors:
        haystack = f"{href} {label} {context}".lower()
        if "json" not in haystack or "csv" in label.lower():
            continue
        data_type = _infer_data_type(f"{href} {label}".lower()) or _infer_data_type(context.lower())
        if not data_type or data_type in seen:
            continue
        candidates.append(DownloadCandidate(data_type=data_type, url=href, label=label or href))
        seen.add(data_type)

    return candidates


def download_usda_json_dump(
    download_page_url: str,
    selected_data_types: tuple[str, ...],
    destination_root: Path,
) -> DownloadResult:
    destination_root.mkdir(parents=True, exist_ok=True)
    html = _read_url(download_page_url).decode("utf-8", errors="replace")
    candidates = discover_usda_json_downloads(html, download_page_url)
    selected = _select_candidates(candidates, selected_data_types)
    if not selected:
        raise RuntimeError(f"No USDA JSON downloads found for: {', '.join(selected_data_types)}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = destination_root / "downloads" / run_id
    archive_dir = run_root / "archives"
    extracted_dir = run_root / "extracted"
    archive_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    for candidate in selected:
        archive_name = _safe_filename(candidate.url.split("/")[-1] or f"{candidate.data_type}.zip")
        archive_path = archive_dir / archive_name
        archive_path.write_bytes(_read_url(candidate.url))
        _extract_zip_safely(archive_path, extracted_dir / _safe_filename(candidate.data_type))

    return DownloadResult(extracted_path=extracted_dir, downloads=selected)


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "food-database-nutrition-agent/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _select_candidates(candidates: list[DownloadCandidate], selected_data_types: tuple[str, ...]) -> list[DownloadCandidate]:
    requested = {item.lower() for item in selected_data_types}
    if "all" in requested:
        return candidates

    output: list[DownloadCandidate] = []
    for candidate in candidates:
        aliases = {candidate.data_type.lower(), *DATA_TYPE_MARKERS[candidate.data_type]}
        if requested.intersection(aliases):
            output.append(candidate)
    return output


def _infer_data_type(value: str) -> str | None:
    for data_type, markers in DATA_TYPE_MARKERS.items():
        if any(marker in value for marker in markers):
            return data_type
    return None


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "download"


def _extract_zip_safely(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = destination / member.filename
            resolved_member_path = member_path.resolve()
            resolved_destination = destination.resolve()
            if resolved_destination not in resolved_member_path.parents and resolved_member_path != resolved_destination:
                raise RuntimeError(f"Unsafe path in USDA archive: {member.filename}")
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, member_path.open("wb") as target:
                shutil.copyfileobj(source, target)
