# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Jupyter Server Documents is a JupyterLab extension that provides real-time collaboration (RTC) capabilities by moving document state to the server. The extension consists of:

- **Python backend** (`jupyter_server_documents/`): Server extension handling WebSocket connections, room management, output processing, and collaboration state
- **TypeScript frontend** (`src/`): JupyterLab extension providing UI components, document providers, and awareness indicators
- **Hybrid architecture**: Frontend builds to `lib/` and gets packaged into `jupyter_server_documents/labextension/`

## Development Commands

### Setup
```bash
# Create development environment
micromamba env create -f dev-environment.yml
micromamba activate serverdocs

# Development installation
jlpm dev:install
```

### Building
```bash
# Build frontend only
jlpm build

# Build for production
jlpm build:prod

# Clean build artifacts
jlpm clean:all
```

### Development Workflow
```bash
# Watch mode (auto-rebuild frontend on changes)
jlpm watch

# Start JupyterLab (in separate terminal)
jupyter lab
```

### Testing
```bash
# Python tests
pytest -vv -r ap --cov jupyter_server_documents

# Frontend tests
jlpm test

# Integration tests (Playwright)
cd ui-tests && yarn test
```

### Code Quality
```bash
# Lint and format
jlpm lint

# Check only (no fixes)
jlpm lint:check
```

## Architecture

### Backend Components
- **`app.py`**: Main server extension (`ServerDocsApp`) - entry point and configuration
- **`rooms/`**: Y-document room management and file-based collaboration state
- **`outputs/`**: Notebook output processing and storage optimization
- **`kernels/`**: Kernel management, execution state, and WebSocket connections
- **`websockets/`**: WebSocket handlers for real-time collaboration
- **`handlers.py`**: HTTP API endpoints

### Frontend Components
- **`src/docprovider/`**: Document providers, awareness, and Y.js integration
- **`src/notebook-factory/`**: Custom notebook model and factory for collaboration
- **`src/codemirror-binding/`**: CodeMirror editor bindings for real-time editing
- **`src/executionindicator.tsx`**: UI component showing execution awareness

### Key Patterns
- Uses **Y.js/Yjs** for conflict-free replicated data types (CRDTs)
- **WebSocket-based** real-time synchronization via `YRoomWebsocket`
- **Output separation**: Large outputs stored separately from notebook documents
- **Awareness protocol**: Shows user cursors and execution state across collaborators
- **Kernel state management**: Handles kernel connections and execution across multiple users

## Development Notes

- After Python changes: restart Jupyter server
- After frontend changes: run `jlpm build` and refresh browser
- Frontend builds to `lib/` then packages to `jupyter_server_documents/labextension/`
- Uses `jlpm` (JupyterLab's yarn) instead of npm/yarn directly
- Development installation uses `uv` for faster Python package management