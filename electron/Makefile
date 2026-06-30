# Meerato desktop (Electron) build & run helpers.
#
# The app points at the hosted instance via the MEERATO_URL env var (see main.js).
# Override it on the command line if needed, e.g.  make start MEERATO_URL=http://localhost:8000

MEERATO_URL ?= https://meerato.com
export MEERATO_URL

NPM ?= npm

.PHONY: help install start pack dist clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	$(NPM) install

start: ## Run the app against $(MEERATO_URL)
	$(NPM) start

pack: ## Build an unpacked app into dist/ (no installer)
	$(NPM) run pack

dist: ## Build distributable installers into dist/
	$(NPM) run dist

clean: ## Remove build output
	rm -rf dist
