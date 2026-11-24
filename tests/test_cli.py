"""Command line: single file, report, batch folders, exit codes, -m entry point."""

import subprocess
import sys

import ezdxf
from conftest import svg

from svg_to_dxf import __version__
from svg_to_dxf.cli import main

PANEL = svg(
    '<rect width="1000" height="500" fill="none" stroke="red"/>'
    '<circle cx="500" cy="250" r="100" fill="none" stroke="blue"/>',
    'width="100mm" height="50mm" viewBox="0 0 1000 500"',
)


def test_single_file_with_report(tmp_path, capsys):
    src = tmp_path / "panel.svg"
    src.write_bytes(PANEL)
    assert main([str(src), "--report"]) == 0
    out = capsys.readouterr().out
    assert "size      100.000 x 50.000 mm  (3.937 x 1.969 in)" in out
    assert "RED_FF0000" in out and "BLUE_0000FF" in out
    assert ezdxf.readfile(tmp_path / "panel.dxf").dxfversion == "AC1024"


def test_output_file_and_flags(tmp_path, capsys):
    src = tmp_path / "panel.svg"
    src.write_bytes(PANEL)
    dst = tmp_path / "out" / "custom.dxf"
    assert main([str(src), "-o", str(dst), "--laser", "--dxf-version", "r2000", "--fit-width", "4in"]) == 0
    doc = ezdxf.readfile(dst)
    assert doc.dxfversion == "AC1015"  # explicit flag beats the --laser preset
    assert "101.600 x 50.800 mm" in capsys.readouterr().out


def test_batch_folder(tmp_path):
    folder = tmp_path / "designs"
    (folder / "sub").mkdir(parents=True)
    for name in ("a.svg", "b.SVG", "sub/c.svg"):
        (folder / name).write_bytes(PANEL)
    (folder / "notes.txt").write_text("not an svg")
    out = tmp_path / "dxf"
    assert main([str(folder), "-o", str(out), "-q"]) == 0
    assert sorted(p.name for p in out.glob("*.dxf")) == ["a.dxf", "b.dxf"]
    assert main([str(folder), "-o", str(out), "-q", "--recursive"]) == 0
    assert (out / "sub" / "c.dxf").exists()


def test_errors_exit_with_code_2(tmp_path, capsys):
    bad = tmp_path / "broken.svg"
    bad.write_text("<svg><path d='M 0 0 L 1 1'")
    good = tmp_path / "good.svg"
    good.write_bytes(PANEL)
    assert main([str(bad), str(good), "-o", str(tmp_path / "out")]) == 2
    assert (tmp_path / "out" / "good.dxf").exists()  # other files still convert
    assert main([str(tmp_path / "missing.svg")]) == 2
    assert main([str(bad), str(good), "-o", str(tmp_path / "x.dxf")]) == 2
    assert "error" in capsys.readouterr().err


def test_python_dash_m(tmp_path):
    src = tmp_path / "panel.svg"
    src.write_bytes(PANEL)
    done = subprocess.run([sys.executable, "-m", "svg_to_dxf", str(src), "-q"], capture_output=True, text=True)
    assert done.returncode == 0 and (tmp_path / "panel.dxf").exists()
    done = subprocess.run([sys.executable, "-m", "svg_to_dxf", "--version"], capture_output=True, text=True)
    assert __version__ in done.stdout
