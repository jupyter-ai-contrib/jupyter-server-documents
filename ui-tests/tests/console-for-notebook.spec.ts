import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  acceptKernelDialog,
  consoleOutputCount,
  createConsoleForNotebook,
  EMPTY_NOTEBOOK,
  openDocument,
  openedDocPath,
  runInConsole,
  uniqueToken
} from './helpers';

/**
 * Don't load the JupyterLab webpage before running the tests, matching the
 * convention in the other specs. Also disable galata's kernel/session/terminal
 * API mocking: unlike the other specs (which run kernel-less), this test spins
 * up a real `python3` kernel, and galata's session-tracking route handler
 * crashes on the live session-creation response under JSD. Setting these to
 * `null` lets the real API responses flow through untouched.
 */
test.use({
  autoGoto: false,
  kernels: null,
  sessions: null,
  terminals: null
});

/** Fixtures used by the test body below. */
type Fixtures = { page: IJupyterLabPageFixture; tmpPath: string };

/**
 * Regression test for
 * jupyter-ai-contrib/jupyter-server-documents#250 (and the upstream
 * jupyterlab/jupyterlab#19010): a code console opened via "New Console for
 * Notebook" renders **no output** when code is executed in it under JSD, while
 * plain JupyterLab and jupyter-server-nbmodel render it correctly.
 *
 * Scenario:
 *   1. Open a notebook with a live `python3` kernel, run `1 + 1` in the first
 *      cell, and assert the cell output is `2` (the notebook path works).
 *   2. Create a console for that notebook (the `notebook:create-console`
 *      command behind the "New Console for Notebook" menu item), sharing the
 *      notebook's kernel.
 *   3. Run `1 + 1` in the console and assert the `2` output renders.
 *
 * The assertions describe the *correct* behavior, so this test fails on a build
 * that still has the bug and passes once it's fixed.
 */
async function consoleForNotebookShowsOutput({
  page,
  tmpPath
}: Fixtures): Promise<void> {
  await page.goto();

  const unique = uniqueToken();
  const nbName = `console-for-nb-${unique}.ipynb`;
  const targetPath = `${tmpPath}/${nbName}`;

  // Create a minimal notebook, open it, and pick a real kernel (the console
  // will inherit it) instead of dismissing the dialog.
  await page.contents.uploadContent(EMPTY_NOTEBOOK, 'text', targetPath);
  await openDocument(page, targetPath);
  await acceptKernelDialog(page, 'python3');
  await openedDocPath(page, nbName);

  // 1. Run `1 + 1` in the notebook's first cell and confirm it outputs `2`.
  await page.notebook.setCell(0, 'code', '1 + 1');
  await page.notebook.runCell(0);
  await page.notebook.waitForRun(0);
  await expect
    .poll(async () => await page.notebook.getCellTextOutput(0), {
      timeout: 30000,
      message: 'notebook cell never produced output'
    })
    .toEqual(expect.arrayContaining([expect.stringContaining('2')]));

  // 2. Open a console for this notebook (shares the notebook's kernel).
  await createConsoleForNotebook(page);

  // 3. Run `1 + 1` in the console and confirm the `2` output renders. The bug
  //    in #250 is that this output never appears under JSD.
  await runInConsole(page, '1 + 1');
  await expect
    .poll(async () => await consoleOutputCount(page, '2'), {
      timeout: 30000,
      message: 'console execution produced no rendered output (issue #250)'
    })
    .toBeGreaterThan(0);
}

test(
  'console created for a notebook renders execution output',
  consoleForNotebookShowsOutput
);
