# Third-party notices

VPN Monitor ships **no bundled third-party code**. It has no runtime pip dependencies. It uses the following libraries as **system dependencies** that the user installs with the system package manager. They are linked dynamically at runtime and never copied into this repository or any release artefact.

Licences below were read from the installed packages with `pacman -Qi` on 2026-11-18 (Arch/Omarchy).

| Component | Installed version | Licence (`pacman -Qi`) | Upstream | Use |
|---|---|---|---|---|
| GTK4 (`gtk4`) | 1:4.24.1-1 | LGPL-2.1-or-later | https://www.gtk.org/ | Overlay window toolkit |
| gtk4-layer-shell (`gtk4-layer-shell`) | 1.3.0-1 | MIT | https://github.com/wmww/gtk4-layer-shell | Click-through layer-shell surface |
| PyGObject (`python-gobject`) | 3.58.1-1 | LGPL-2.1-or-later | https://pygobject.gnome.org/ | Python bindings for GTK4 |

## Development-only tools
Development tools (uv, pytest, ruff, mypy, pre-commit, gitleaks) are used on the developer's machine and in CI only. They are not distributed with the project. They are added here, with their licences, when Phase 02 pins them.

## Keeping this file accurate
Check licences before adding any dependency (see `CLAUDE.md`), and update this table in the same change.

## Development-only dependencies (Phase 02, 2026-11-18 22:19 CST)
Installed by `uv sync` from `uv.lock` for local development and CI only. They are **not** shipped, bundled or imported by the `vpn-monitor` package. Licences read from each package's installed metadata.

| Package | Locked version | Licence |
|---|---|---|
| pytest | 9.2.0 | MIT |
| pytest-cov | 7.1.0 | MIT |
| coverage | 7.17.3 | Apache-2.0 |
| ruff | 0.17.5 | MIT |
| mypy | 2.4.1 | MIT |
| mypy-extensions | 1.2.0 | MIT |
| librt | 0.16.0 | MIT |
| ast-serialize | 0.13.1 | MIT |
| pathspec | 1.1.1 | MPL-2.0 |
| pluggy | 1.7.0 | MIT |
| iniconfig | 2.3.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pygments | 2.21.0 | BSD-2-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| colorama | 0.4.6 | BSD-3-Clause (Windows only; not installed here) |
