import shutil

from scripts import build


def test_portable_archive_contains_importable_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "os_tag", lambda: "windows")
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "szi.exe").write_bytes(b"test")
    output = build.assemble(app_dir)
    assert (output / "data" / "seed_bundle.json").read_bytes() == (
        build.ROOT / "data" / "seed_bundle.json"
    ).read_bytes()
    unpacked = tmp_path / "unpacked"
    shutil.unpack_archive(str(output) + ".zip", unpacked)
    assert (unpacked / output.name / "data" / "seed_bundle.json").exists()
