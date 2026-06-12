import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ITranslator } from '@jupyterlab/translation';
import { URLExt } from '@jupyterlab/coreutils';
import { IDocumentProviderFactory } from '@jupyter/docprovider';
import { User } from '@jupyterlab/services';
import { WebSocketProvider } from './yprovider';

export const jsdDocumentProviderFactory: JupyterFrontEndPlugin<IDocumentProviderFactory> =
  {
    id: '@jupyter-ai-contrib/server-documents:document-provider-factory',
    description: 'Provides the JSD WebSocket document provider factory.',
    provides: IDocumentProviderFactory,
    requires: [ITranslator],
    activate: (
      app: JupyterFrontEnd,
      translator: ITranslator
    ): IDocumentProviderFactory => {
      const trans = translator.load('jupyter_collaboration');
      return {
        create(options: IDocumentProviderFactory.IOptions) {
          return new WebSocketProvider({
            app,
            url: URLExt.join(
              (options.serverSettings ?? app.serviceManager.serverSettings)
                .wsUrl,
              'api/collaboration/room'
            ),
            path: options.path,
            format: options.format,
            contentType: options.contentType,
            model: options.model,
            user: options.user as unknown as User.IManager,
            translator: trans
          });
        }
      };
    }
  };
