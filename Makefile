# Slopsmith — Common Operations
# Usage: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Configuration ─────────────────────────────────────────────────────────────
SLOPSMITH_PORT ?= 8000
DLC_PATH ?= ~/.local/share/Steam/steamapps/common/Rocksmith2014/dlc
COMPOSE := docker compose
IMAGE_NAME := slopsmith
BASE_URL := http://localhost:$(SLOPSMITH_PORT)

# Plugin dev: set PLUGIN_DIR to mount an external plugin into the container
PLUGIN_DIR ?=

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

# ── Container Lifecycle ───────────────────────────────────────────────────────
.PHONY: dev down rebuild logs shell status restart

dev: ## Start slopsmith dev container (live-reload mounts)
	DLC_PATH="$(DLC_PATH)" $(COMPOSE) up -d --build
	@echo "Slopsmith running at $(BASE_URL)"

down: ## Stop slopsmith containers
	$(COMPOSE) down

rebuild: ## Full rebuild (no cache) and restart
	$(COMPOSE) down
	DLC_PATH="$(DLC_PATH)" $(COMPOSE) build --no-cache --progress=plain
	DLC_PATH="$(DLC_PATH)" $(COMPOSE) up -d
	@echo "Rebuilt and running at $(BASE_URL)"

restart: ## Restart containers without rebuild
	$(COMPOSE) restart
	@echo "Restarted at $(BASE_URL)"

logs: ## Tail container logs (Ctrl-C to stop)
	$(COMPOSE) logs -f --tail=100

shell: ## Open a bash shell inside the running container
	$(COMPOSE) exec web bash

status: ## Show container status and health
	@$(COMPOSE) ps
	@echo ""
	@curl -sf $(BASE_URL)/api/scan-status 2>/dev/null && echo "" || echo "Server not responding at $(BASE_URL)"

# ── NAS Deployment ────────────────────────────────────────────────────────────
.PHONY: nas-deploy nas-down nas-logs

nas-deploy: ## Deploy to NAS (uses docker-compose.nas.yml)
	$(COMPOSE) -f docker-compose.nas.yml up -d --build
	@echo "NAS deployment running"

nas-down: ## Stop NAS deployment
	$(COMPOSE) -f docker-compose.nas.yml down

nas-logs: ## Tail NAS container logs
	$(COMPOSE) -f docker-compose.nas.yml logs -f --tail=100

# ── Plugin Development ────────────────────────────────────────────────────────
.PHONY: dev-plugin plugin-scaffold plugin-list plugin-logs

dev-plugin: ## Start slopsmith with PLUGIN_DIR mounted (PLUGIN_DIR=../my-plugin make dev-plugin)
ifndef PLUGIN_DIR
	$(error PLUGIN_DIR is required. Usage: PLUGIN_DIR=../slopsmith-plugin-foo make dev-plugin)
endif
	@PLUGIN_NAME=$$(basename "$(PLUGIN_DIR)"); \
	PLUGIN_ABS=$$(cd "$(PLUGIN_DIR)" && pwd); \
	echo "Mounting plugin from $$PLUGIN_ABS"; \
	DLC_PATH="$(DLC_PATH)" \
	SLOPSMITH_PORT=$(SLOPSMITH_PORT) \
	$(COMPOSE) \
		-f docker-compose.yml \
		-f <(echo "services:" && \
		     echo "  web:" && \
		     echo "    ports:" && \
		     echo "      - \"$(SLOPSMITH_PORT):8000\"" && \
		     echo "    volumes:" && \
		     echo "      - $$PLUGIN_ABS:/app/plugins/$$PLUGIN_NAME" && \
		     echo "    environment:" && \
		     echo "      - SLOPSMITH_PLUGINS_DIR=/app/plugins") \
		up -d --build
	@echo "Slopsmith + plugin running at http://localhost:$(SLOPSMITH_PORT)"

plugin-scaffold: ## Scaffold a new plugin (NAME=myplugin make plugin-scaffold)
ifndef NAME
	$(error NAME is required. Usage: NAME=myplugin make plugin-scaffold)
endif
	@./scripts/scaffold-plugin.sh "$(NAME)"

plugin-list: ## List loaded plugins via API
	@curl -sf $(BASE_URL)/api/plugins | python3 -m json.tool 2>/dev/null || echo "Server not running"

plugin-updates: ## Check for plugin updates via API
	@curl -sf $(BASE_URL)/api/plugins/updates | python3 -m json.tool 2>/dev/null || echo "Server not running"

# ── Library Management ────────────────────────────────────────────────────────
.PHONY: rescan rescan-full scan-status library-stats

rescan: ## Trigger incremental library rescan
	@curl -sf -X POST $(BASE_URL)/api/rescan | python3 -m json.tool
	@echo "Rescan started. Use 'make scan-status' to monitor."

rescan-full: ## Trigger full library rescan (rebuilds all metadata)
	@curl -sf -X POST $(BASE_URL)/api/rescan/full | python3 -m json.tool
	@echo "Full rescan started."

scan-status: ## Show current scan progress
	@curl -sf $(BASE_URL)/api/scan-status | python3 -m json.tool 2>/dev/null || echo "Server not running"

library-stats: ## Show library statistics
	@curl -sf $(BASE_URL)/api/library/stats | python3 -m json.tool 2>/dev/null || echo "Server not running"

artists: ## List all artists in library
	@curl -sf $(BASE_URL)/api/library/artists | python3 -m json.tool 2>/dev/null || echo "Server not running"

# ── Search / Browse ───────────────────────────────────────────────────────────
.PHONY: search

search: ## Search library (Q="search term" make search)
ifndef Q
	$(error Q is required. Usage: Q="metallica" make search)
endif
	@curl -sf "$(BASE_URL)/api/library?q=$(Q)&page_size=20" | \
		python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"{s['artist']} — {s['title']}\") for s in d.get('songs',[])]" \
		2>/dev/null || echo "Server not running"

# ── Conversion Tools ──────────────────────────────────────────────────────────
.PHONY: psarc-to-sloppak split-stems

psarc-to-sloppak: ## Convert PSARC to sloppak (SRC=file.psarc DST=output/ make psarc-to-sloppak)
ifndef SRC
	$(error SRC is required. Usage: SRC=file.psarc DST=./out make psarc-to-sloppak)
endif
	python3 scripts/psarc_to_sloppak.py "$(SRC)" $(if $(DST),--output "$(DST)")

split-stems: ## Split audio into stems (SRC=file.ogg make split-stems)
ifndef SRC
	$(error SRC is required. Usage: SRC=audio.ogg make split-stems)
endif
	python3 scripts/split_stems.py "$(SRC)"

# ── Development ───────────────────────────────────────────────────────────────
.PHONY: lint test dejavu

lint: ## Lint Python code
	@python3 -m py_compile server.py && echo "server.py OK" || echo "server.py FAIL"
	@for f in lib/*.py; do python3 -m py_compile "$$f" && echo "$$f OK" || echo "$$f FAIL"; done

test: ## Run tests (if any exist)
	@if [ -f pytest.ini ] || [ -f setup.cfg ] || [ -d tests ]; then \
		python3 -m pytest -v; \
	else \
		echo "No test suite found."; \
	fi

dejavu: ## Analyze Claude Code sessions for this project (shows automation gaps)
	@python3 ~/src/dejavu/dejavu --project . --recent 5

dejavu-all: ## Analyze all Claude Code sessions for this project
	@python3 ~/src/dejavu/dejavu --project . --all

# ── Docker Image ──────────────────────────────────────────────────────────────
.PHONY: build tag push

build: ## Build docker image
	docker build --progress=plain -t $(IMAGE_NAME) .

tag: ## Tag image for registry (REGISTRY=ghcr.io/user make tag)
ifndef REGISTRY
	$(error REGISTRY is required. Usage: REGISTRY=ghcr.io/ahonnecke make tag)
endif
	docker tag $(IMAGE_NAME) $(REGISTRY)/$(IMAGE_NAME):latest

# ── Settings ──────────────────────────────────────────────────────────────────
.PHONY: settings

settings: ## Show current slopsmith settings
	@curl -sf $(BASE_URL)/api/settings | python3 -m json.tool 2>/dev/null || echo "Server not running"
