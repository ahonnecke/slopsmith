#!/usr/bin/env bash
# Scaffold a new slopsmith plugin directory with boilerplate files.
# Usage: ./scripts/scaffold-plugin.sh <plugin-name>

set -euo pipefail

NAME="${1:?Usage: scaffold-plugin.sh <plugin-name>}"
PLUGIN_ID="${NAME}"
PLUGIN_DIR="../slopsmith-plugin-${NAME}"

if [ -d "$PLUGIN_DIR" ]; then
    echo "ERROR: Directory already exists: $PLUGIN_DIR"
    exit 1
fi

echo "Creating plugin scaffold at $PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR"

# plugin.json — manifest
cat > "$PLUGIN_DIR/plugin.json" <<EOF
{
    "id": "${PLUGIN_ID}",
    "name": "${NAME^}",
    "nav": "${NAME^}",
    "screen": "screen.html",
    "script": "screen.js",
    "version": "0.1.0",
    "description": "Slopsmith ${NAME} plugin"
}
EOF

# screen.html — plugin UI panel
cat > "$PLUGIN_DIR/screen.html" <<EOF
<div id="${PLUGIN_ID}-root" class="p-4">
    <h2 class="text-xl font-bold mb-4">${NAME^}</h2>
    <p class="text-gray-400">Plugin loaded.</p>
</div>
EOF

# screen.js — plugin script (draws on highway, handles events)
cat > "$PLUGIN_DIR/screen.js" <<EOF
// ${NAME^} plugin for Slopsmith
// Hooks: onDraw(ctx, state), onNoteHit(note), onInit(api)

(function () {
    'use strict';

    return {
        onInit(api) {
            console.log('[${NAME}] initialized');
        },

        onDraw(ctx, state) {
            // Called each frame during highway rendering.
            // ctx: CanvasRenderingContext2D
            // state: { currentTime, notes, anchors, ... }
        },

        onDestroy() {
            console.log('[${NAME}] destroyed');
        }
    };
})();
EOF

# routes.py — optional FastAPI routes
cat > "$PLUGIN_DIR/routes.py" <<'EOF'
"""Server-side routes for the plugin."""

from fastapi import FastAPI


def setup(app: FastAPI, context: dict):
    """Register plugin API routes."""

    @app.get(f"/api/plugins/${PLUGIN_ID}/status")
    def plugin_status():
        return {"status": "ok"}
EOF
# Fix the route path to use the actual plugin ID
sed -i "s|\${PLUGIN_ID}|${PLUGIN_ID}|g" "$PLUGIN_DIR/routes.py"

# Makefile — plugin-level dev commands
cat > "$PLUGIN_DIR/Makefile" <<'MAKEFILE'
SHELL := /bin/bash
SLOPSMITH_DIR ?= ../slopsmith
SLOPSMITH_PORT ?= 8088

.PHONY: dev down logs test

dev: ## Start slopsmith with this plugin mounted
	PLUGIN_DIR=$(CURDIR) SLOPSMITH_PORT=$(SLOPSMITH_PORT) make -C $(SLOPSMITH_DIR) dev-plugin

down: ## Stop slopsmith
	make -C $(SLOPSMITH_DIR) down

logs: ## Tail slopsmith logs
	make -C $(SLOPSMITH_DIR) logs

test: ## Run plugin tests
	@if [ -f package.json ]; then npm test; \
	elif [ -d tests ]; then python3 -m pytest tests/ -v; \
	else echo "No tests found"; fi
MAKEFILE

# README.md
cat > "$PLUGIN_DIR/README.md" <<EOF
# slopsmith-plugin-${NAME}

Slopsmith plugin: ${NAME^}

## Development

\`\`\`bash
# Start slopsmith with this plugin
make dev

# View logs
make logs

# Stop
make down
\`\`\`

## Structure

- \`plugin.json\` — Plugin manifest
- \`screen.html\` — UI panel
- \`screen.js\` — Client-side script (highway hooks)
- \`routes.py\` — Server-side API routes (optional)
EOF

# .gitignore
cat > "$PLUGIN_DIR/.gitignore" <<EOF
__pycache__/
*.pyc
node_modules/
.venv/
EOF

# Initialize git repo
cd "$PLUGIN_DIR"
git init -q
git add -A
git commit -q -m "Initial scaffold for slopsmith-plugin-${NAME}"

echo ""
echo "Plugin scaffolded at: $PLUGIN_DIR"
echo ""
echo "Next steps:"
echo "  cd $PLUGIN_DIR"
echo "  make dev          # Start slopsmith with plugin mounted"
echo "  make logs         # Watch logs"
