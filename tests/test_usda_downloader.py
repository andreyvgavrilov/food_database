import json
import zipfile

from app.usda.downloader import discover_usda_json_downloads, download_usda_json_dump


def test_discover_usda_json_downloads_selects_json_links():
    html = """
    <section>
      <h2>Foundation Foods</h2>
      <a href="/fdc-datasets/foundation-foods-json.zip">April 2026 (JSON)</a>
      <a href="/fdc-datasets/foundation-foods-csv.zip">April 2026 (CSV)</a>
      <h2>SR Legacy</h2>
      <a href="/fdc-datasets/sr-legacy-json.zip">April 2026 (JSON)</a>
    </section>
    """

    downloads = discover_usda_json_downloads(html, "https://fdc.nal.usda.gov/download-datasets/")

    assert [(download.data_type, download.url) for download in downloads] == [
        ("Foundation Foods", "https://fdc.nal.usda.gov/fdc-datasets/foundation-foods-json.zip"),
        ("SR Legacy", "https://fdc.nal.usda.gov/fdc-datasets/sr-legacy-json.zip"),
    ]


def test_download_usda_json_dump_extracts_selected_archives(tmp_path, monkeypatch):
    foundation_archive = tmp_path / "foundation.zip"
    with zipfile.ZipFile(foundation_archive, "w") as archive:
        archive.writestr(
            "foundation.json",
            json.dumps({"FoundationFoods": [{"fdcId": 1, "description": "Apple"}]}),
        )

    html = f"""
    <h2>Foundation Foods</h2>
    <a href="{foundation_archive.as_uri()}">April 2026 (JSON)</a>
    <h2>Branded</h2>
    <a href="https://example.test/branded.zip">April 2026 (JSON)</a>
    """

    def fake_read_url(url):
        if url == "https://fdc.example.test/download-datasets/":
            return html.encode("utf-8")
        if url == foundation_archive.as_uri():
            return foundation_archive.read_bytes()
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("app.usda.downloader._read_url", fake_read_url)

    result = download_usda_json_dump(
        "https://fdc.example.test/download-datasets/",
        ("Foundation Foods",),
        tmp_path / "destination",
    )

    extracted_json = list(result.extracted_path.rglob("*.json"))
    assert len(extracted_json) == 1
    assert json.loads(extracted_json[0].read_text(encoding="utf-8"))["FoundationFoods"][0]["description"] == "Apple"
    assert result.downloads[0].data_type == "Foundation Foods"
