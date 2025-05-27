# jupyter_server_documents

[![Github Actions Status](https://github.com/jupyter-ai-contrib/jupyter_server_documents/workflows/Build/badge.svg)](https://github.com/jupyter-ai-contrib/jupyter_server_documents/actions/workflows/build.yml)

A JupyterLab extension that provides RTC capabilities.

This extension is composed of a Python package named `jupyter_server_documents`
for the server extension and a NPM package named `@jupyter/server-documents`
for the frontend extension.

## Try it out

Run with the proper configuration

```
jupyter lab --config jupyter_config.py
```

## Requirements

- JupyterLab >= 4.0.0

## Installation

To install the extension, run:

```bash
pip install jupyter_server_documents
```

To remove the extension, run:

```bash
pip uninstall jupyter_server_documents
```

## Contributing

### Setting up a development environment

We recommend using
[Micromamba](https://mamba.readthedocs.io/en/latest/user_guide/micromamba.html)
to create and manage a custom Python environment for developing this package.
Micromamba provides most of the same CLI as Conda, but works much faster.

First, set up a development environment by running this command from the root of
this repository:

```sh
micromamba env create -f dev-environment.yml
```

This creates a new Python environment named `serverdocs` and automatically installs
this extension's build dependencies, required for local development. Then,
activate the environment:

```sh
micromamba activate serverdocs
```

Activating an environment is required to access any Python packages installed in
that environment. You should activate the environment before developing any
changes to the `jupyter_server_documents` package locally.

### Development install

After ensuring that the `serverdocs` environment is activated, you can install an
editable copy of `jupyter_server_documents` into your environment by running the script
below.

```bash
jlpm dev:install
```

Notes about the development installation:

- `jlpm` is JupyterLab's pinned version of [yarn](https://yarnpkg.com/) that is
  installed with JupyterLab. In other words, `jlpm` can be considered an alias of
  `yarn`.

- `jlpm dev:install` runs the `dev:install` NPM script defined in `package.json`.

- The `dev:install` step uses [`uv`](https://docs.astral.sh/uv/) as a faster,
  more modern replacement for `pip`.

After completing this, you should have a working, editable copy of
`jupyter_server_documents` in your environment. Run `jupyter lab` and open JupyterLab in
a browser to verify that `jupyter_server_documents` is installed.

### Development process

When making new changes to your local copy of `jupyter_server_documents`, different
commands need to be run depending on the types of changes made. Without running
these commands, the new changes are not reflected in JupyterLab.

Here is a summary of the commands to run after making changes:

- After updating `package.json` or `yarn.lock`: run `jlpm install` to install
  the frontend dependencies.

- After updating any frontend (TS/TSX/JS/CSS): run `jlpm build` to build the lab
  extension (i.e. the frontend).

- After updating any backend (Python) file: restart the server to reload the
  server extension (i.e. the backend).

  - Note that there is no build process when updating a Python file, since
    Python is a scripting language.

- After updating entry points or other package metadata in `pyproject.toml`: run
  `jlpm dev:uninstall && jlpm dev:install` to re-do the development installation.
  The package metadata is not updated automatically after local changes, even when
  installing the package in editable mode.

- Finally, refresh the JupyterLab page in the browser to load the new
  frontend assets and use the new backend.

### Building on change (frontend only)

You can watch the source directory and run JupyterLab at the same time in
different terminals to watch for changes in the extension's source and
automatically rebuild the extension.

```bash
# Watch the source directory in one terminal, automatically rebuilding when needed
jlpm watch
# Run JupyterLab in another terminal
jupyter lab
```

With the watch command running, every saved change will immediately be built
locally and available in your running JupyterLab. Refresh JupyterLab to load the
change in your browser (you may need to wait several seconds for the extension
to be rebuilt).

By default, the `jlpm build` command generates the source maps for this
extension to make it easier to debug using the browser dev tools. To also
generate source maps for the JupyterLab core extensions, you can run the
following command:

```bash
jupyter lab build --minimize=False
```

Note that the steps described here only update the application in response to
changes to frontend (TypeScript) files. Changes to any backend (Python) files
still require restarting the Jupyter Server.

### Development uninstall

To undo the development installation, run this command:

```bash
jlpm dev:uninstall
```

In development mode, you will also need to remove the symlink created by
`jupyter labextension develop` command. To find its location, you can run
`jupyter labextension list` to figure out where the `labextensions` folder is
located. Then you can remove the symlink named `@jupyter/server-documents` within that
folder.

### Testing the extension

#### Server tests

This extension is using [Pytest](https://docs.pytest.org/) for Python code testing.

Install test dependencies (needed only once):

```sh
pip install -e ".[test]"
# Each time you install the Python package, you need to restore the front-end extension link
jupyter labextension develop . --overwrite
```

To execute them, run:

```sh
pytest -vv -r ap --cov jupyter_server_documents
```

#### Frontend tests

This extension is using [Jest](https://jestjs.io/) for JavaScript code testing.

To execute them, execute:

```sh
jlpm
jlpm test
```

#### Integration tests

This extension uses [Playwright](https://playwright.dev/docs/intro) for the integration tests (aka user level tests).
More precisely, the JupyterLab helper [Galata](https://github.com/jupyterlab/jupyterlab/tree/master/galata) is used to handle testing the extension in JupyterLab.

More information are provided within the [ui-tests](./ui-tests/README.md) README.

### Packaging the extension

See [RELEASE](RELEASE.md)

## Troubleshooting

If you are seeing the frontend extension, but it is not working, check
that the server extension is enabled:

```bash
jupyter server extension list
```

If the server extension is installed and enabled, but you are not seeing
the frontend extension, check the frontend extension is installed:

```bash
jupyter labextension list
```
