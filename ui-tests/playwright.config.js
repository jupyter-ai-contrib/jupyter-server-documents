/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require('@jupyterlab/galata/lib/playwright-config');

// Run the test server on a dedicated port so it never reuses or collides with
// a JupyterLab dev server on the default 8888.
const PORT = 8899;

module.exports = {
  ...baseConfig,
  use: { ...baseConfig.use, baseURL: `http://localhost:${PORT}` },
  webServer: {
    command: `jlpm start --port=${PORT}`,
    url: `http://localhost:${PORT}/lab`,
    timeout: 120 * 1000,
    reuseExistingServer: false
  }
};
