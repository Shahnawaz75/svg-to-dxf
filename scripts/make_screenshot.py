"""Build docs/screenshot.png: the SVG rendered by a browser next to the DXF.

    pip install -e ".[docs]"
    python scripts/make_screenshot.py [--browser PATH]

Left: examples/box-panel.svg rendered by headless Microsoft Edge (or Chrome).
Right: the converted DXF read back and drawn by ezdxf's drawing add-on, with
layer colors and the measured bounding box. Both sides are real output.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from svg_to_dxf import convert  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "examples" / "box-panel.svg"
OUT = ROOT / "docs" / "screenshot.png"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "msedge",
    "microsoft-edge",
    "google-chrome",
    "chromium",
    "chromium-browser",
]


def find_browser(explicit: str | None) -> str:
    for candidate in [explicit] if explicit else BROWSERS:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    raise SystemExit("no Edge/Chrome found; pass --browser PATH")


def render_svg(svg: Path, browser: str, work: Path, width: int = 960, height: int = 600) -> Path:
    """Screenshot the SVG in a headless browser (fresh, temporary profile)."""
    shutil.copy(svg, work / svg.name)
    page = work / "page.html"
    page.write_text(
        '<!doctype html><html><body style="margin:0;background:#fff">'
        f'<img src="{svg.name}" style="width:{width}px;height:{height}px;object-fit:contain">'
        "</body></html>",
        encoding="utf-8",
    )
    png = work / "svg.png"
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--force-device-scale-factor=2",
        f"--user-data-dir={work / 'profile'}",
        f"--screenshot={png}",
        f"--window-size={width},{height}",
        page.as_uri(),
    ]
    subprocess.run(cmd, check=True, timeout=180, capture_output=True)
    return png


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", help="path to msedge/chrome")
    args = parser.parse_args()
    browser = find_browser(args.browser)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        svg_png = render_svg(SVG, browser, work)
        result = convert(SVG, work / "box-panel.dxf")  # default settings, read back below
        doc = ezdxf.readfile(work / "box-panel.dxf")

        fig, (left, right) = plt.subplots(1, 2, figsize=(16, 6.3), dpi=100)
        fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.11, wspace=0.03)
        left.imshow(plt.imread(svg_png))
        left.set_axis_off()
        left.set_title("SVG  (examples/box-panel.svg in Microsoft Edge)", fontsize=13)

        config = Configuration(background_policy=BackgroundPolicy.WHITE, min_lineweight=1.4)
        backend = MatplotlibBackend(right, adjust_figure=False)
        Frontend(RenderContext(doc), backend, config=config).draw_layout(doc.modelspace(), finalize=True)
        x0, y0, x1, y1 = result.extents
        dim = dict(arrowstyle="<|-|>", color="#222222", lw=1, shrinkA=0, shrinkB=0, mutation_scale=12)
        right.annotate("", xy=(x0, y0 - 5), xytext=(x1, y0 - 5), arrowprops=dim)
        right.text((x0 + x1) / 2, y0 - 7, f"{x1 - x0:.3f} mm", ha="center", va="top", fontsize=12)
        right.annotate("", xy=(x1 + 5, y0), xytext=(x1 + 5, y1), arrowprops=dim)
        right.text(x1 + 7, (y0 + y1) / 2, f"{y1 - y0:.3f} mm", ha="left", va="center", rotation=90, fontsize=12)
        right.set_xlim(x0 - 5, x1 + 15)
        right.set_ylim(y0 - 14, y1 + 5)
        right.set_aspect("equal", adjustable="box")
        right.set_axis_off()
        handles = []
        for name, stats in result.layers.items():
            rgb = doc.layers.get(name).rgb or (0, 0, 0)
            types = ", ".join(f"{k} {v}" for k, v in sorted(stats.types.items()))
            handles.append(Patch(color=[c / 255 for c in rgb], label=f"layer {name}: {types}"))
        right.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=1, frameon=False, fontsize=11)
        right.set_title("DXF  (box-panel.dxf read back with ezdxf: R2010, mm)", fontsize=13)
        OUT.parent.mkdir(exist_ok=True)
        fig.savefig(OUT, dpi=100, facecolor="white")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
