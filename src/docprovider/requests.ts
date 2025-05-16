/* -----------------------------------------------------------------------------
| Copyright (c) Jupyter Development Team.
| Distributed under the terms of the Modified BSD License.
|----------------------------------------------------------------------------*/

import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection, Contents } from '@jupyterlab/services';

/**
 * Document session endpoint provided by `jupyter_collaboration`
 * See https://github.com/jupyterlab/jupyter_collaboration
 */
// const DOC_SESSION_URL = 'api/collaboration/session';

/**
 * Document session model
 */
export interface ISessionModel {
  /**
   * Document format; 'text', 'base64',...
   */
  format: Contents.FileFormat;
  /**
   * Document type
   */
  type: Contents.ContentType;
  /**
   * File unique identifier
   */
  fileId: string;
  /**
   * Server session identifier
   */
  sessionId: string;
}

/**
 * Call the API extension
 *
 * @param endPoint API REST end point for the extension
 * @param init Initial values for the request
 * @returns The response body interpreted as JSON
 */
export async function requestAPI<T = any>(
  endPoint = '',
  init: RequestInit = {}
): Promise<T> {
  // Make request to Jupyter API
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(settings.baseUrl, endPoint);

  let response: Response;
  try {
    response = await ServerConnection.makeRequest(requestUrl, init, settings);
  } catch (error) {
    throw new ServerConnection.NetworkError(error as any);
  }

  let data: any = await response.text();

  if (data.length > 0) {
    try {
      data = JSON.parse(data);
    } catch (error) {
      console.error('Not a JSON response body.', response);
    }
  }

  if (!response.ok) {
    throw new ServerConnection.ResponseError(response, data.message || data);
  }

  return data;
}
