/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require('@jupyterlab/galata/lib/playwright-config');

// Run the test server on a dedicated port so it never reuses or collides with
// a JupyterLab dev server on the default 8888.
const PORT = 8899;

module.exports = {
  ...baseConfig,
  // Repeat every test to surface flakiness in the timing-sensitive
  // reconnect / divergent-sync tests. Defaults to 3 on CI, 1 locally; override
  // with JSD_TEST_REPEATS, or pass `--repeat-each=N` for ad-hoc flake hunting.
  repeatEach: Number(process.env.JSD_TEST_REPEATS ?? (process.env.CI ? 3 : 1)),
  use: { ...baseConfig.use, baseURL: `http://localhost:${PORT}` },
  webServer: {
    command: `jlpm start --port=${PORT}`,
    url: `http://localhost:${PORT}/lab`,
    timeout: 120 * 1000,
    reuseExistingServer: false
  }
};
