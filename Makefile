# tmux-status — local test/lint runner.
#
# Per the project's testing policy, the full suite runs LOCALLY (not in GitHub
# Actions). `make test` is the canonical green gate used by the pre-push hook:
# bash syntax + the model unit tests + the render-daemon unit tests + the
# render pipeline integration test.
#
#   make test         # the green gate (run before pushing)
#   make test-server  # full server/tests suite (may need extra deps: webtest, curl_cffi)
#   make lint         # shellcheck all shell scripts (if installed)

.PHONY: test test-server lint

test:
	@echo "── bash syntax gate ──"
	@bash tests/unit/test_syntax.sh
	@echo "── status.conf reader contract gate ──"
	@bash tests/unit/test_status_conf_contract.sh
	@echo "── model unit tests ──"
	@python3 -m unittest discover -s tests/unit -p 'test_*.py'
	@echo "── render daemon unit tests ──"
	@cd server/tests && python3 -m unittest test_render test_singleton test_render_deploy
	@echo "── poke (daemon wake) unit test ──"
	@bash tests/unit/test_poke.sh
	@echo "── render pipeline integration ──"
	@bash tests/integration/test_render_pipeline.sh
	@echo "✓ make test passed"

test-server:
	@python3 -m unittest discover -s server/tests -p 'test_*.py'

lint:
	@command -v shellcheck >/dev/null 2>&1 && \
		find scripts -type f \( -name '*.sh' -o -exec grep -lq '^#!/usr/bin/env bash' {} \; \) -print0 \
		| xargs -0 shellcheck -S warning install.sh uninstall.sh || \
		echo "shellcheck not installed; skipping"
