# HANDOFF — TS-54 ready for centralized verification

## Implemented

- `install.sh` cleans validated setuptools `build/` and `*.egg-info` paths before
  every strategy, recreates pipx/uv/stdlib environments, and verifies installed
  Python modules plus the distribution dependency closure.
- Package dependency coverage is an exact allowlist instead of a dead-package
  denylist.
- `uninstall.sh` removes the pipx app and dedicated fallback venv. It no longer
  mutates an unrelated system Python or hides cleanup failures.
- Package metadata now describes the Claude CLI collector.
- New shell gates cover staged orphans, installed module/dependency orphans,
  installer structure, and uninstaller ownership/failure behavior.

## Focused commits

- `7bd7987` — clean builds, fresh environments, installed-artifact verification.
- `584ddde` — managed-environment uninstall behavior.
- Final documentation/test commit follows this handoff update.

## Tests run

- `bash tests/unit/test_build_artifacts.sh`
- `bash tests/unit/test_install_venv_hygiene.sh`
- `bash tests/unit/test_uninstall_venv.sh`
- `bash tests/unit/test_syntax.sh`
- `bash tests/unit/test_install_dir.sh`
- `bash tests/unit/test_install_noninteractive.sh`
- `cd server/tests && python3 -m unittest test_package`
- Shellcheck on every changed shell script/test.

All passed in the TS-54 worktree. The full `make test` suite was intentionally
not run here.

## Central verifier owns

1. Run the full suite.
2. Review and merge the linked TS-54 pull request with a merge commit.
3. Complete TS-54 and clean its worktree.

No version, release, deployment, or live installation was performed.
