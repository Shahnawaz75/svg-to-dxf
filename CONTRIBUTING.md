# Contributing to svg-to-dxf

Thanks for helping. Bug reports, small SVG files that convert badly, and pull requests
are all welcome.

## Reporting a problem

Open an issue with:

- the command you ran (or the Python call) and the full output, ideally with `--report`;
- the smallest SVG that shows the problem (please remove anything private);
- what you expected (for example "the circle should be 10 mm") and what you got;
- the program you imported the DXF into, if it rejected the file or showed it wrongly.

## Development setup

```bash
git clone https://github.com/Shahnawaz75/svg-to-dxf
cd svg-to-dxf
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Code layout

| File | Role |
| --- | --- |
| `src/svg_to_dxf/svgread.py` | SVG -> geometry in document space (svgelements, visibility, layers) |
| `src/svg_to_dxf/geometry.py` | affine maps, segments, flattening, B-splines, joining |
| `src/svg_to_dxf/writer.py` | geometry -> DXF entities per version, layers, statistics |
| `src/svg_to_dxf/converter.py` | the pipeline, `convert()` and the report |
| `src/svg_to_dxf/options.py` | options, validation, the `--laser` preset |
| `src/svg_to_dxf/cli.py` | command line and batch conversion |

## Tests

Every behavior is tested with a small SVG that has a known answer: the test converts it,
reads the DXF back with ezdxf, runs `doc.audit()`, and compares geometry with tight
tolerances (usually 1e-9 mm). Please add such a test with every fix or feature. See
`tests/conftest.py` for the `run` fixture.

## Examples and screenshot

If a change affects output, regenerate the examples and check the diff:

```bash
python examples/make_examples.py
pip install -e ".[docs]"
python scripts/make_screenshot.py   # needs Microsoft Edge or Chrome
```

## Pull requests

- Keep changes focused; one topic per pull request.
- Use type hints and short docstrings; match the existing style.
- Update `README.md` and `CHANGELOG.md` when behavior changes.
- The tool must stay offline: no network access at runtime.

By contributing you agree that your contributions are licensed under the MIT License.
