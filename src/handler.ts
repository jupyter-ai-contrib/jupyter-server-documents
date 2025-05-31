import { URLExt } from '@jupyterlab/coreutils';

import { ServerConnection } from '@jupyterlab/services';

/**
 * Call the API extension
 *
 * @param endPoint API REST end point for the extension
 * @param init Initial values for the request
 * @returns The response body interpreted as JSON
 */
export async function requestAPI<T>(
  endPoint = '',
  init: RequestInit = {}
): Promise<T> {
  // Make request to Jupyter API
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(
    settings.baseUrl,
    endPoint.startsWith('/') ? '' : 'jupyter-server-documents', // API Namespace
    endPoint
  );

  let response: Response;
  try {
    response = await ServerConnection.makeRequest(requestUrl, init, settings);
  } catch (error) {
    throw new ServerConnection.NetworkError(error as any);
  }

  const contentType = response.headers.get('Content-Type') || '';
  let data: any;

  // Read response text
  const responseText = await response.text();

  if (contentType.includes('application/x-ndjson')) {
    data = responseText
      .trim()
      .split('\n')
      .map(line => JSON.parse(line));
  } else if (responseText.length > 0) {
    try {
      data = JSON.parse(responseText);
    } catch (error) {
      console.log('Not a JSON response body.', response);
    }
  }

  if (!response.ok) {
    throw new ServerConnection.ResponseError(response, data.message || data);
  }

  return data;
}
