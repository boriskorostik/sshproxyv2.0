# AGENT.md

## Scope
Work only inside `/home/boris/script/ssh_proxv2.0`.

## Active Files
- `sshproxyv2.0.py` - original full version
- `sshproxy_lite.py` - reduced version
- `sshproxy_leonid.py` - Leonid-specific version
- `*.spec` - PyInstaller build specs
- `AppDir*` - AppImage staging directories

## Build
- Syntax check:
  `python3 -m py_compile sshproxy_lite.py sshproxy_leonid.py`
- Lite build:
  `.venv/bin/pyinstaller --clean --noconfirm sshproxy_lite.spec`
- Leonid build:
  `.venv/bin/pyinstaller --clean --noconfirm sshproxy_leonid.spec`
- AppImage packaging uses `appimagetool-x86_64.AppImage`.

## Working Rules
- Do not modify `sshproxyv2.0.py` unless explicitly requested.
- Prefer creating separate variants instead of mixing special-case behavior into the original file.
- Keep UI changes small and intentional.
- Rebuild the relevant AppImage after changing Python code.

## Git Hygiene
- Do not commit `.venv/`, `build/`, `dist/`, or generated AppImages unless the user explicitly wants release artifacts versioned.
- Keep source, spec files, and lightweight metadata in git.
