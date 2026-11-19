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
