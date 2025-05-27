"use strict";
(self["webpackChunk_jupyter_rtc_core"] = self["webpackChunk_jupyter_rtc_core"] || []).push([["lib_index_js"],{

/***/ "./lib/docprovider/awareness.js":
/*!**************************************!*\
  !*** ./lib/docprovider/awareness.js ***!
  \**************************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   WebSocketAwarenessProvider: () => (/* binding */ WebSocketAwarenessProvider)
/* harmony export */ });
/* harmony import */ var y_websocket__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! y-websocket */ "webpack/sharing/consume/default/y-websocket/y-websocket");
/* harmony import */ var y_websocket__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(y_websocket__WEBPACK_IMPORTED_MODULE_0__);
/* -----------------------------------------------------------------------------
| Copyright (c) Jupyter Development Team.
| Distributed under the terms of the Modified BSD License.
|----------------------------------------------------------------------------*/

/**
 * A class to provide Yjs synchronization over WebSocket.
 *
 * We specify custom messages that the server can interpret. For reference please look in yjs_ws_server.
 *
 */
class WebSocketAwarenessProvider extends y_websocket__WEBPACK_IMPORTED_MODULE_0__.WebsocketProvider {
    /**
     * Construct a new WebSocketAwarenessProvider
     *
     * @param options The instantiation options for a WebSocketAwarenessProvider
     */
    constructor(options) {
        super(options.url, options.roomID, options.awareness.doc, {
            awareness: options.awareness
        });
        this._isDisposed = false;
        this._awareness = options.awareness;
        this._user = options.user;
        this._user.ready
            .then(() => this._onUserChanged(this._user))
            .catch(e => console.error(e));
        this._user.userChanged.connect(this._onUserChanged, this);
    }
    get isDisposed() {
        return this._isDisposed;
    }
    dispose() {
        if (this._isDisposed) {
            return;
        }
        this._user.userChanged.disconnect(this._onUserChanged, this);
        this._isDisposed = true;
        this.destroy();
    }
    _onUserChanged(user) {
        this._awareness.setLocalStateField('user', user.identity);
    }
}


/***/ }),

/***/ "./lib/docprovider/filebrowser.js":
/*!****************************************!*\
  !*** ./lib/docprovider/filebrowser.js ***!
  \****************************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   logger: () => (/* binding */ logger),
/* harmony export */   rtcContentProvider: () => (/* binding */ rtcContentProvider),
/* harmony export */   yfile: () => (/* binding */ yfile),
/* harmony export */   ynotebook: () => (/* binding */ ynotebook)
/* harmony export */ });
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/apputils */ "webpack/sharing/consume/default/@jupyterlab/apputils");
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_fileeditor__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/fileeditor */ "webpack/sharing/consume/default/@jupyterlab/fileeditor");
/* harmony import */ var _jupyterlab_fileeditor__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_fileeditor__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyterlab_logconsole__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyterlab/logconsole */ "webpack/sharing/consume/default/@jupyterlab/logconsole");
/* harmony import */ var _jupyterlab_logconsole__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_logconsole__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @jupyterlab/notebook */ "webpack/sharing/consume/default/@jupyterlab/notebook");
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__);
/* harmony import */ var _jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! @jupyterlab/settingregistry */ "webpack/sharing/consume/default/@jupyterlab/settingregistry");
/* harmony import */ var _jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_4___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_4__);
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(/*! @jupyterlab/translation */ "webpack/sharing/consume/default/@jupyterlab/translation");
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5__);
/* harmony import */ var _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_6__ = __webpack_require__(/*! @jupyter/ydoc */ "webpack/sharing/consume/default/@jupyter/ydoc");
/* harmony import */ var _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_6___default = /*#__PURE__*/__webpack_require__.n(_jupyter_ydoc__WEBPACK_IMPORTED_MODULE_6__);
/* harmony import */ var _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__ = __webpack_require__(/*! @jupyter/collaborative-drive */ "webpack/sharing/consume/default/@jupyter/collaborative-drive/@jupyter/collaborative-drive");
/* harmony import */ var _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7___default = /*#__PURE__*/__webpack_require__.n(_jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__);
/* harmony import */ var _ydrive__WEBPACK_IMPORTED_MODULE_8__ = __webpack_require__(/*! ./ydrive */ "./lib/docprovider/ydrive.js");
/*
 * Copyright (c) Jupyter Development Team.
 * Distributed under the terms of the Modified BSD License.
 */









const TWO_SESSIONS_WARNING = 'The file %1 has been opened with two different views. ' +
    'This is not supported. Please close this view; otherwise, ' +
    'some of your edits may not be saved properly.';
const rtcContentProvider = {
    id: '@jupyter-rtc-core/docprovider-extension:content-provider',
    description: 'The RTC content provider',
    provides: _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__.ICollaborativeContentProvider,
    requires: [_jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5__.ITranslator],
    optional: [_jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__.IGlobalAwareness],
    activate: (app, translator, globalAwareness) => {
        const trans = translator.load('jupyter_collaboration');
        const defaultDrive = app.serviceManager.contents
            .defaultDrive;
        if (!defaultDrive) {
            throw Error('Cannot initialize content provider: default drive property not accessible on contents manager instance.');
        }
        const registry = defaultDrive.contentProviderRegistry;
        if (!registry) {
            throw Error('Cannot initialize content provider: no content provider registry.');
        }
        const rtcContentProvider = new _ydrive__WEBPACK_IMPORTED_MODULE_8__.RtcContentProvider({
            apiEndpoint: '/api/contents',
            serverSettings: defaultDrive.serverSettings,
            user: app.serviceManager.user,
            trans,
            globalAwareness
        });
        registry.register('rtc', rtcContentProvider);
        return rtcContentProvider;
    }
};
/**
 * Plugin to register the shared model factory for the content type 'file'.
 */
const yfile = {
    id: '@jupyter-rtc-core/docprovider-extension:yfile',
    description: "Plugin to register the shared model factory for the content type 'file'",
    autoStart: true,
    requires: [_jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__.ICollaborativeContentProvider, _jupyterlab_fileeditor__WEBPACK_IMPORTED_MODULE_1__.IEditorWidgetFactory],
    activate: (app, contentProvider, editorFactory) => {
        const yFileFactory = () => {
            return new _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_6__.YFile();
        };
        contentProvider.sharedModelFactory.registerDocumentFactory('file', yFileFactory);
        editorFactory.contentProviderId = 'rtc';
    }
};
/**
 * Plugin to register the shared model factory for the content type 'notebook'.
 */
const ynotebook = {
    id: '@jupyter/rtc-core/docprovider-extension:ynotebook',
    description: "Plugin to register the shared model factory for the content type 'notebook'",
    autoStart: true,
    requires: [_jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_7__.ICollaborativeContentProvider, _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__.INotebookWidgetFactory],
    optional: [_jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_4__.ISettingRegistry],
    activate: (app, contentProvider, notebookFactory, settingRegistry) => {
        let disableDocumentWideUndoRedo = true;
        // Fetch settings if possible.
        if (settingRegistry) {
            settingRegistry
                .load('@jupyterlab/notebook-extension:tracker')
                .then(settings => {
                const updateSettings = (settings) => {
                    const enableDocWideUndo = settings === null || settings === void 0 ? void 0 : settings.get('experimentalEnableDocumentWideUndoRedo').composite;
                    disableDocumentWideUndoRedo = !(enableDocWideUndo !== null && enableDocWideUndo !== void 0 ? enableDocWideUndo : false);
                };
                updateSettings(settings);
                settings.changed.connect((settings) => updateSettings(settings));
            });
        }
        const yNotebookFactory = () => {
            return new _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_6__.YNotebook({
                disableDocumentWideUndoRedo
            });
        };
        contentProvider.sharedModelFactory.registerDocumentFactory('notebook', yNotebookFactory);
        notebookFactory.contentProviderId = 'rtc';
    }
};
/**
 * The default collaborative drive provider.
 */
const logger = {
    id: '@jupyter/rtc-core/docprovider-extension:logger',
    description: 'A logging plugin for debugging purposes.',
    autoStart: true,
    optional: [_jupyterlab_logconsole__WEBPACK_IMPORTED_MODULE_2__.ILoggerRegistry, _jupyterlab_fileeditor__WEBPACK_IMPORTED_MODULE_1__.IEditorTracker, _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__.INotebookTracker, _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5__.ITranslator],
    activate: (app, loggerRegistry, fileTracker, nbTracker, translator) => {
        const trans = (translator !== null && translator !== void 0 ? translator : _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_5__.nullTranslator).load('jupyter_collaboration');
        const schemaID = 'https://schema.jupyter.org/jupyter_collaboration/session/v1';
        if (!loggerRegistry) {
            app.serviceManager.events.stream.connect((_, emission) => {
                var _a, _b;
                if (emission.schema_id === schemaID) {
                    console.debug(`[${emission.room}(${emission.path})] ${(_a = emission.action) !== null && _a !== void 0 ? _a : ''}: ${(_b = emission.msg) !== null && _b !== void 0 ? _b : ''}`);
                    if (emission.level === 'WARNING') {
                        (0,_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.showDialog)({
                            title: trans.__('Warning'),
                            body: trans.__(TWO_SESSIONS_WARNING, emission.path),
                            buttons: [_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.Dialog.okButton()]
                        });
                    }
                }
            });
            return;
        }
        const loggers = new Map();
        const addLogger = (sender, document) => {
            const logger = loggerRegistry.getLogger(document.context.path);
            loggers.set(document.context.localPath, logger);
            document.disposed.connect(document => {
                loggers.delete(document.context.localPath);
            });
        };
        if (fileTracker) {
            fileTracker.widgetAdded.connect(addLogger);
        }
        if (nbTracker) {
            nbTracker.widgetAdded.connect(addLogger);
        }
        void (async () => {
            var _a, _b;
            const { events } = app.serviceManager;
            for await (const emission of events.stream) {
                if (emission.schema_id === schemaID) {
                    const logger = loggers.get(emission.path);
                    logger === null || logger === void 0 ? void 0 : logger.log({
                        type: 'text',
                        level: emission.level.toLowerCase(),
                        data: `[${emission.room}] ${(_a = emission.action) !== null && _a !== void 0 ? _a : ''}: ${(_b = emission.msg) !== null && _b !== void 0 ? _b : ''}`
                    });
                    if (emission.level === 'WARNING') {
                        (0,_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.showDialog)({
                            title: trans.__('Warning'),
                            body: trans.__(TWO_SESSIONS_WARNING, emission.path),
                            buttons: [_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.Dialog.warnButton({ label: trans.__('Ok') })]
                        });
                    }
                }
            }
        })();
    }
};


/***/ }),

/***/ "./lib/docprovider/requests.js":
/*!*************************************!*\
  !*** ./lib/docprovider/requests.js ***!
  \*************************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   requestAPI: () => (/* binding */ requestAPI)
/* harmony export */ });
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/coreutils */ "webpack/sharing/consume/default/@jupyterlab/coreutils");
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/services */ "webpack/sharing/consume/default/@jupyterlab/services");
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__);
/* -----------------------------------------------------------------------------
| Copyright (c) Jupyter Development Team.
| Distributed under the terms of the Modified BSD License.
|----------------------------------------------------------------------------*/


/**
 * Call the API extension
 *
 * @param endPoint API REST end point for the extension
 * @param init Initial values for the request
 * @returns The response body interpreted as JSON
 */
async function requestAPI(endPoint = '', init = {}) {
    // Make request to Jupyter API
    const settings = _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.makeSettings();
    const requestUrl = _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__.URLExt.join(settings.baseUrl, endPoint);
    let response;
    try {
        response = await _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.makeRequest(requestUrl, init, settings);
    }
    catch (error) {
        throw new _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.NetworkError(error);
    }
    let data = await response.text();
    if (data.length > 0) {
        try {
            data = JSON.parse(data);
        }
        catch (error) {
            console.error('Not a JSON response body.', response);
        }
    }
    if (!response.ok) {
        throw new _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.ResponseError(response, data.message || data);
    }
    return data;
}


/***/ }),

/***/ "./lib/docprovider/ydrive.js":
/*!***********************************!*\
  !*** ./lib/docprovider/ydrive.js ***!
  \***********************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   RtcContentProvider: () => (/* binding */ RtcContentProvider)
/* harmony export */ });
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/coreutils */ "webpack/sharing/consume/default/@jupyterlab/coreutils");
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/services */ "webpack/sharing/consume/default/@jupyterlab/services");
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _lumino_signaling__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @lumino/signaling */ "webpack/sharing/consume/default/@lumino/signaling");
/* harmony import */ var _lumino_signaling__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_lumino_signaling__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var _yprovider__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! ./yprovider */ "./lib/docprovider/yprovider.js");
// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.




const DISABLE_RTC = _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__.PageConfig.getOption('disableRTC') === 'true' ? true : false;
/**
 * The url for the default drive service.
 */
const DOCUMENT_PROVIDER_URL = 'api/collaboration/room';
class RtcContentProvider extends _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.RestContentProvider {
    constructor(options) {
        super(options);
        this._onCreate = (options, sharedModel) => {
            var _a, _b;
            if (typeof options.format !== 'string') {
                return;
            }
            try {
                const provider = new _yprovider__WEBPACK_IMPORTED_MODULE_3__.WebSocketProvider({
                    url: _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__.URLExt.join(this._serverSettings.wsUrl, DOCUMENT_PROVIDER_URL),
                    path: options.path,
                    format: options.format,
                    contentType: options.contentType,
                    model: sharedModel,
                    user: this._user,
                    translator: this._trans
                });
                // Add the document path in the list of opened ones for this user.
                const state = ((_a = this._globalAwareness) === null || _a === void 0 ? void 0 : _a.getLocalState()) || {};
                const documents = state.documents || [];
                if (!documents.includes(options.path)) {
                    documents.push(options.path);
                    (_b = this._globalAwareness) === null || _b === void 0 ? void 0 : _b.setLocalStateField('documents', documents);
                }
                const key = `${options.format}:${options.contentType}:${options.path}`;
                this._providers.set(key, provider);
                sharedModel.changed.connect(async (_, change) => {
                    var _a;
                    if (!change.stateChange) {
                        return;
                    }
                    const hashChanges = change.stateChange.filter(change => change.name === 'hash');
                    if (hashChanges.length === 0) {
                        return;
                    }
                    if (hashChanges.length > 1) {
                        console.error('Unexpected multiple changes to hash value in a single transaction');
                    }
                    const hashChange = hashChanges[0];
                    // A change in hash signifies that a save occurred on the server-side
                    // (e.g. a collaborator performed the save) - we want to notify the
                    // observers about this change so that they can store the new hash value.
                    const newPath = (_a = sharedModel.state.path) !== null && _a !== void 0 ? _a : options.path;
                    const model = await this.get(newPath, { content: false });
                    this._ydriveFileChanged.emit({
                        type: 'save',
                        newValue: { ...model, hash: hashChange.newValue },
                        // we do not have the old model because it was discarded when server made the change,
                        // we only have the old hash here (which may be empty if the file was newly created!)
                        oldValue: { hash: hashChange.oldValue }
                    });
                });
                sharedModel.disposed.connect(() => {
                    var _a, _b;
                    const provider = this._providers.get(key);
                    if (provider) {
                        provider.dispose();
                        this._providers.delete(key);
                    }
                    // Remove the document path from the list of opened ones for this user.
                    const state = ((_a = this._globalAwareness) === null || _a === void 0 ? void 0 : _a.getLocalState()) || {};
                    const documents = state.documents || [];
                    const index = documents.indexOf(options.path);
                    if (index > -1) {
                        documents.splice(index, 1);
                    }
                    (_b = this._globalAwareness) === null || _b === void 0 ? void 0 : _b.setLocalStateField('documents', documents);
                });
            }
            catch (error) {
                // Falling back to the contents API if opening the websocket failed
                //  This may happen if the shared document is not a YDocument.
                console.error(`Failed to open websocket connection for ${options.path}.\n:${error}`);
            }
        };
        this._ydriveFileChanged = new _lumino_signaling__WEBPACK_IMPORTED_MODULE_2__.Signal(this);
        this._user = options.user;
        this._trans = options.trans;
        this._globalAwareness = options.globalAwareness;
        this._serverSettings = options.serverSettings;
        this.sharedModelFactory = new SharedModelFactory(this._onCreate);
        this._providers = new Map();
    }
    get providers() {
        return this._providers;
    }
    /**
     * Get a file or directory.
     *
     * @param localPath: The path to the file.
     *
     * @param options: The options used to fetch the file.
     *
     * @returns A promise which resolves with the file content.
     */
    async get(localPath, options) {
        if (options && options.format && options.type) {
            const key = `${options.format}:${options.type}:${localPath}`;
            const provider = this._providers.get(key);
            if (provider) {
                // If the document doesn't exist, `super.get` will reject with an
                // error and the provider will never be resolved.
                // Use `Promise.all` to reject as soon as possible. The Context will
                // show a dialog to the user.
                const [model] = await Promise.all([
                    super.get(localPath, { ...options, content: false }),
                    provider.ready
                ]);
                // The server doesn't return a model with a format when content is false,
                // so set it back.
                return { ...model, format: options.format };
            }
        }
        return super.get(localPath, options);
    }
    /**
     * Save a file.
     *
     * @param localPath - The desired file path.
     *
     * @param options - Optional overrides to the model.
     *
     * @returns A promise which resolves with the file content model when the
     *   file is saved.
     */
    async save(localPath, options = {}) {
        // Check that there is a provider - it won't e.g. if the document model is not collaborative.
        if (options.format && options.type) {
            const key = `${options.format}:${options.type}:${localPath}`;
            const provider = this._providers.get(key);
            if (provider) {
                // Save is done from the backend
                const fetchOptions = {
                    type: options.type,
                    format: options.format,
                    content: false
                };
                return this.get(localPath, fetchOptions);
            }
        }
        return super.save(localPath, options);
    }
    /**
     * A signal emitted when a file operation takes place.
     */
    get fileChanged() {
        return this._ydriveFileChanged;
    }
}
/**
 * Yjs sharedModel factory for real-time collaboration.
 */
class SharedModelFactory {
    /**
     * Shared model factory constructor
     *
     * @param _onCreate Callback on new document model creation
     */
    constructor(_onCreate) {
        this._onCreate = _onCreate;
        /**
         * Whether the IDrive supports real-time collaboration or not.
         */
        this.collaborative = !DISABLE_RTC;
        this.documentFactories = new Map();
    }
    /**
     * Register a SharedDocumentFactory.
     *
     * @param type Document type
     * @param factory Document factory
     */
    registerDocumentFactory(type, factory) {
        if (this.documentFactories.has(type)) {
            throw new Error(`The content type ${type} already exists`);
        }
        this.documentFactories.set(type, factory);
    }
    /**
     * Create a new `ISharedDocument` instance.
     *
     * It should return `undefined` if the factory is not able to create a `ISharedDocument`.
     */
    createNew(options) {
        if (typeof options.format !== 'string') {
            console.warn(`Only defined format are supported; got ${options.format}.`);
            return;
        }
        if (!this.collaborative || !options.collaborative) {
            // Bail if the document model does not support collaboration
            // the `sharedModel` will be the default one.
            return;
        }
        if (this.documentFactories.has(options.contentType)) {
            const factory = this.documentFactories.get(options.contentType);
            const sharedModel = factory(options);
            this._onCreate(options, sharedModel);
            return sharedModel;
        }
        return;
    }
}


/***/ }),

/***/ "./lib/docprovider/yprovider.js":
/*!**************************************!*\
  !*** ./lib/docprovider/yprovider.js ***!
  \**************************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   WebSocketProvider: () => (/* binding */ WebSocketProvider)
/* harmony export */ });
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/apputils */ "webpack/sharing/consume/default/@jupyterlab/apputils");
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _lumino_coreutils__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @lumino/coreutils */ "webpack/sharing/consume/default/@lumino/coreutils");
/* harmony import */ var _lumino_coreutils__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_lumino_coreutils__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _lumino_signaling__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @lumino/signaling */ "webpack/sharing/consume/default/@lumino/signaling");
/* harmony import */ var _lumino_signaling__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_lumino_signaling__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var y_websocket__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! y-websocket */ "webpack/sharing/consume/default/y-websocket/y-websocket");
/* harmony import */ var y_websocket__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(y_websocket__WEBPACK_IMPORTED_MODULE_3__);
/* harmony import */ var _requests__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ./requests */ "./lib/docprovider/requests.js");
/* -----------------------------------------------------------------------------
| Copyright (c) Jupyter Development Team.
| Distributed under the terms of the Modified BSD License.
|----------------------------------------------------------------------------*/





/**
 * A class to provide Yjs synchronization over WebSocket.
 *
 * We specify custom messages that the server can interpret. For reference please look in yjs_ws_server.
 *
 */
class WebSocketProvider {
    /**
     * Construct a new WebSocketProvider
     *
     * @param options The instantiation options for a WebSocketProvider
     */
    constructor(options) {
        /**
         * Handles disconnections from the YRoom Websocket.
         *
         * TODO: handle disconnections more gracefully by reseting the YDoc to an
         * empty state on disconnect. Unfortunately the shared model does not provide
         * any methods for this, so we are just asking disconnected clients to
         * refresh for now.
         *
         * TODO: distinguish between disconnects when server YDoc history is the same
         * (i.e. SS1 + SS2 is sufficient), and when the history
         * differs (client's YDoc has to be reset before SS1 + SS2).
         */
        this._onConnectionClosed = (event) => {
            // Log error to console for debugging
            console.error('WebSocket connection was closed. Close event: ', event);
            // Show dialog to tell user to refresh the page
            (0,_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.showErrorMessage)(this._trans.__('Document session error'), 'Please refresh the browser tab.', [_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.Dialog.okButton()]);
            // Delete this client's YDoc by disposing of the shared model.
            // This is the only way we know of to stop `y-websocket` from constantly
            // attempting to re-connect.
            this._sharedModel.dispose();
        };
        this._onSync = (isSynced) => {
            if (isSynced) {
                if (this._yWebsocketProvider) {
                    this._yWebsocketProvider.off('sync', this._onSync);
                    const state = this._sharedModel.ydoc.getMap('state');
                    state.set('document_id', this._yWebsocketProvider.roomname);
                }
                this._ready.resolve();
            }
        };
        this._ready = new _lumino_coreutils__WEBPACK_IMPORTED_MODULE_1__.PromiseDelegate();
        this._isDisposed = false;
        this._path = options.path;
        this._contentType = options.contentType;
        this._format = options.format;
        this._serverUrl = options.url;
        this._sharedModel = options.model;
        this._awareness = options.model.awareness;
        this._yWebsocketProvider = null;
        this._trans = options.translator;
        const user = options.user;
        user.ready
            .then(() => {
            this._onUserChanged(user);
        })
            .catch(e => console.error(e));
        user.userChanged.connect(this._onUserChanged, this);
        this._connect().catch(e => console.warn(e));
    }
    /**
     * Test whether the object has been disposed.
     */
    get isDisposed() {
        return this._isDisposed;
    }
    /**
     * A promise that resolves when the document provider is ready.
     */
    get ready() {
        return this._ready.promise;
    }
    get contentType() {
        return this._contentType;
    }
    get format() {
        return this._format;
    }
    /**
     * Dispose of the resources held by the object.
     */
    dispose() {
        var _a, _b, _c;
        if (this.isDisposed) {
            return;
        }
        this._isDisposed = true;
        (_a = this._yWebsocketProvider) === null || _a === void 0 ? void 0 : _a.off('connection-close', this._onConnectionClosed);
        (_b = this._yWebsocketProvider) === null || _b === void 0 ? void 0 : _b.off('sync', this._onSync);
        (_c = this._yWebsocketProvider) === null || _c === void 0 ? void 0 : _c.destroy();
        this._disconnect();
        _lumino_signaling__WEBPACK_IMPORTED_MODULE_2__.Signal.clearData(this);
    }
    async reconnect() {
        this._disconnect();
        this._connect();
    }
    async _connect() {
        // Fetch file ID from the file ID service.
        const resp = await (0,_requests__WEBPACK_IMPORTED_MODULE_4__.requestAPI)(`api/fileid/index?path=${this._path}`, {
            method: 'POST'
        });
        const fileId = resp['id'];
        this._yWebsocketProvider = new y_websocket__WEBPACK_IMPORTED_MODULE_3__.WebsocketProvider(this._serverUrl, `${this._format}:${this._contentType}:${fileId}`, this._sharedModel.ydoc, {
            disableBc: true,
            // params: { sessionId: session.sessionId },
            awareness: this._awareness
        });
        this._yWebsocketProvider.on('sync', this._onSync);
        this._yWebsocketProvider.on('connection-close', this._onConnectionClosed);
    }
    get wsProvider() {
        return this._yWebsocketProvider;
    }
    _disconnect() {
        var _a, _b, _c;
        (_a = this._yWebsocketProvider) === null || _a === void 0 ? void 0 : _a.off('connection-close', this._onConnectionClosed);
        (_b = this._yWebsocketProvider) === null || _b === void 0 ? void 0 : _b.off('sync', this._onSync);
        (_c = this._yWebsocketProvider) === null || _c === void 0 ? void 0 : _c.destroy();
        this._yWebsocketProvider = null;
    }
    _onUserChanged(user) {
        this._awareness.setLocalStateField('user', user.identity);
    }
}


/***/ }),

/***/ "./lib/executionindicator.js":
/*!***********************************!*\
  !*** ./lib/executionindicator.js ***!
  \***********************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   AwarenessExecutionIndicator: () => (/* binding */ AwarenessExecutionIndicator)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "webpack/sharing/consume/default/react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/translation */ "webpack/sharing/consume/default/@jupyterlab/translation");
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyterlab/ui-components */ "webpack/sharing/consume/default/@jupyterlab/ui-components");
/* harmony import */ var _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @jupyterlab/notebook */ "webpack/sharing/consume/default/@jupyterlab/notebook");
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__);
// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.




/**
 * A VDomRenderer widget for displaying the execution status.
 */
class AwarenessExecutionIndicator extends _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__.VDomRenderer {
    /**
     * Construct the kernel status widget.
     */
    constructor(translator, showProgress = true) {
        super(new AwarenessExecutionIndicator.Model());
        this.translator = translator || _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__.nullTranslator;
        this.addClass('jp-mod-highlighted');
    }
    /**
     * Render the execution status item.
     */
    render() {
        if (this.model === null || !this.model.renderFlag) {
            return react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null);
        }
        else {
            const nb = this.model.currentNotebook;
            if (!nb) {
                return (react__WEBPACK_IMPORTED_MODULE_0___default().createElement(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__.ExecutionIndicatorComponent, { displayOption: this.model.displayOption, state: undefined, translator: this.translator }));
            }
            return (react__WEBPACK_IMPORTED_MODULE_0___default().createElement(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__.ExecutionIndicatorComponent, { displayOption: this.model.displayOption, state: this.model.executionState(nb), translator: this.translator }));
        }
    }
}
(function (AwarenessExecutionIndicator) {
    class Model extends _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_3__.ExecutionIndicator.Model {
        /**
         * A weak map to hold execution status of multiple notebooks.
         */
        // (this as any) casts are required to avoid 
        // ts errors when accessing private methods
        attachNotebook(data) {
            var _a;
            const nb = data === null || data === void 0 ? void 0 : data.content;
            if (!nb) {
                return;
            }
            this._currentNotebook = nb;
            this._notebookExecutionProgress.set(nb, {
                executionStatus: 'idle',
                kernelStatus: 'idle',
                totalTime: 0,
                interval: 0,
                timeout: 0,
                scheduledCell: new Set(),
                scheduledCellNumber: 0,
                needReset: true
            });
            const state = this._notebookExecutionProgress.get(nb);
            const contextStatusChanged = (ctx) => {
                var _a;
                if (state) {
                    const awarenessStates = (_a = nb === null || nb === void 0 ? void 0 : nb.model) === null || _a === void 0 ? void 0 : _a.sharedModel.awareness.getStates();
                    if (awarenessStates) {
                        for (const [_, clientState] of awarenessStates) {
                            if ('kernel' in clientState) {
                                state.kernelStatus = clientState['kernel']['execution_state'];
                                this.stateChanged.emit(void 0);
                                return;
                            }
                        }
                    }
                }
            };
            (_a = nb === null || nb === void 0 ? void 0 : nb.model) === null || _a === void 0 ? void 0 : _a.sharedModel.awareness.on('change', contextStatusChanged);
            super.attachNotebook(data);
        }
    }
    AwarenessExecutionIndicator.Model = Model;
})(AwarenessExecutionIndicator || (AwarenessExecutionIndicator = {}));


/***/ }),

/***/ "./lib/handler.js":
/*!************************!*\
  !*** ./lib/handler.js ***!
  \************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   requestAPI: () => (/* binding */ requestAPI)
/* harmony export */ });
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/coreutils */ "webpack/sharing/consume/default/@jupyterlab/coreutils");
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/services */ "webpack/sharing/consume/default/@jupyterlab/services");
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__);


/**
 * Call the API extension
 *
 * @param endPoint API REST end point for the extension
 * @param init Initial values for the request
 * @returns The response body interpreted as JSON
 */
async function requestAPI(endPoint = '', init = {}) {
    // Make request to Jupyter API
    const settings = _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.makeSettings();
    const requestUrl = _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_0__.URLExt.join(settings.baseUrl, endPoint.startsWith('/') ? '' : 'jupyter-rtc-core', // API Namespace
    endPoint);
    let response;
    try {
        response = await _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.makeRequest(requestUrl, init, settings);
    }
    catch (error) {
        throw new _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.NetworkError(error);
    }
    let data = await response.text();
    if (data.length > 0) {
        try {
            data = JSON.parse(data);
        }
        catch (error) {
            console.log('Not a JSON response body.', response);
        }
    }
    if (!response.ok) {
        throw new _jupyterlab_services__WEBPACK_IMPORTED_MODULE_1__.ServerConnection.ResponseError(response, data.message || data);
    }
    return data;
}


/***/ }),

/***/ "./lib/index.js":
/*!**********************!*\
  !*** ./lib/index.js ***!
  \**********************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "default": () => (__WEBPACK_DEFAULT_EXPORT__),
/* harmony export */   executionIndicator: () => (/* binding */ executionIndicator),
/* harmony export */   kernelStatus: () => (/* binding */ kernelStatus),
/* harmony export */   plugin: () => (/* binding */ plugin),
/* harmony export */   rtcGlobalAwarenessPlugin: () => (/* binding */ rtcGlobalAwarenessPlugin)
/* harmony export */ });
/* harmony import */ var _jupyterlab_application__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/application */ "webpack/sharing/consume/default/@jupyterlab/application");
/* harmony import */ var _jupyterlab_application__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_application__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/settingregistry */ "webpack/sharing/consume/default/@jupyterlab/settingregistry");
/* harmony import */ var _jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyterlab/notebook */ "webpack/sharing/consume/default/@jupyterlab/notebook");
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var _jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @jupyterlab/statusbar */ "webpack/sharing/consume/default/@jupyterlab/statusbar");
/* harmony import */ var _jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_3__);
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! @jupyterlab/translation */ "webpack/sharing/consume/default/@jupyterlab/translation");
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4__);
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(/*! @jupyterlab/apputils */ "webpack/sharing/consume/default/@jupyterlab/apputils");
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__);
/* harmony import */ var _executionindicator__WEBPACK_IMPORTED_MODULE_15__ = __webpack_require__(/*! ./executionindicator */ "./lib/executionindicator.js");
/* harmony import */ var _jupyterlab_codeeditor__WEBPACK_IMPORTED_MODULE_6__ = __webpack_require__(/*! @jupyterlab/codeeditor */ "webpack/sharing/consume/default/@jupyterlab/codeeditor");
/* harmony import */ var _jupyterlab_codeeditor__WEBPACK_IMPORTED_MODULE_6___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_codeeditor__WEBPACK_IMPORTED_MODULE_6__);
/* harmony import */ var _handler__WEBPACK_IMPORTED_MODULE_13__ = __webpack_require__(/*! ./handler */ "./lib/handler.js");
/* harmony import */ var _notebook__WEBPACK_IMPORTED_MODULE_17__ = __webpack_require__(/*! ./notebook */ "./lib/notebook.js");
/* harmony import */ var _docprovider__WEBPACK_IMPORTED_MODULE_18__ = __webpack_require__(/*! ./docprovider */ "./lib/docprovider/filebrowser.js");
/* harmony import */ var _jupyterlab_statedb__WEBPACK_IMPORTED_MODULE_7__ = __webpack_require__(/*! @jupyterlab/statedb */ "webpack/sharing/consume/default/@jupyterlab/statedb");
/* harmony import */ var _jupyterlab_statedb__WEBPACK_IMPORTED_MODULE_7___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_statedb__WEBPACK_IMPORTED_MODULE_7__);
/* harmony import */ var _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_8__ = __webpack_require__(/*! @jupyter/collaborative-drive */ "webpack/sharing/consume/default/@jupyter/collaborative-drive/@jupyter/collaborative-drive");
/* harmony import */ var _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_8___default = /*#__PURE__*/__webpack_require__.n(_jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_8__);
/* harmony import */ var yjs__WEBPACK_IMPORTED_MODULE_9__ = __webpack_require__(/*! yjs */ "webpack/sharing/consume/default/yjs");
/* harmony import */ var yjs__WEBPACK_IMPORTED_MODULE_9___default = /*#__PURE__*/__webpack_require__.n(yjs__WEBPACK_IMPORTED_MODULE_9__);
/* harmony import */ var y_protocols_awareness__WEBPACK_IMPORTED_MODULE_10__ = __webpack_require__(/*! y-protocols/awareness */ "./node_modules/y-protocols/awareness.js");
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_11__ = __webpack_require__(/*! @jupyterlab/services */ "webpack/sharing/consume/default/@jupyterlab/services");
/* harmony import */ var _jupyterlab_services__WEBPACK_IMPORTED_MODULE_11___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_services__WEBPACK_IMPORTED_MODULE_11__);
/* harmony import */ var _docprovider_awareness__WEBPACK_IMPORTED_MODULE_14__ = __webpack_require__(/*! ./docprovider/awareness */ "./lib/docprovider/awareness.js");
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_12__ = __webpack_require__(/*! @jupyterlab/coreutils */ "webpack/sharing/consume/default/@jupyterlab/coreutils");
/* harmony import */ var _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_12___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_12__);
/* harmony import */ var _kernelstatus__WEBPACK_IMPORTED_MODULE_16__ = __webpack_require__(/*! ./kernelstatus */ "./lib/kernelstatus.js");




















/**
 * Initialization data for the @jupyter/rtc-core extension.
 */
const plugin = {
    id: '@jupyter/rtc-core:plugin',
    description: 'A JupyterLab extension that provides RTC capabilities.',
    autoStart: true,
    optional: [_jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_1__.ISettingRegistry],
    activate: (app, settingRegistry) => {
        console.log('JupyterLab extension @jupyter/rtc-core is activated!');
        if (settingRegistry) {
            settingRegistry
                .load(plugin.id)
                .then(settings => {
                console.log('@jupyter/rtc-core settings loaded:', settings.composite);
            })
                .catch(reason => {
                console.error('Failed to load settings for @jupyter/rtc-core.', reason);
            });
        }
        (0,_handler__WEBPACK_IMPORTED_MODULE_13__.requestAPI)('get-example')
            .then(data => {
            console.log(data);
        })
            .catch(reason => {
            console.error(`The jupyter_rtc_core server extension appears to be missing.\n${reason}`);
        });
    }
};
/**
 * Jupyter plugin creating a global awareness for RTC.
 */
const rtcGlobalAwarenessPlugin = {
    id: '@jupyter/rtc-core/collaboration-extension:rtcGlobalAwareness',
    description: 'Add global awareness to share working document of users.',
    requires: [_jupyterlab_statedb__WEBPACK_IMPORTED_MODULE_7__.IStateDB],
    provides: _jupyter_collaborative_drive__WEBPACK_IMPORTED_MODULE_8__.IGlobalAwareness,
    activate: (app, state) => {
        const { user } = app.serviceManager;
        const ydoc = new yjs__WEBPACK_IMPORTED_MODULE_9__.Doc();
        const awareness = new y_protocols_awareness__WEBPACK_IMPORTED_MODULE_10__.Awareness(ydoc);
        // TODO: Uncomment once global awareness is working
        const server = _jupyterlab_services__WEBPACK_IMPORTED_MODULE_11__.ServerConnection.makeSettings();
        const url = _jupyterlab_coreutils__WEBPACK_IMPORTED_MODULE_12__.URLExt.join(server.wsUrl, 'api/collaboration/room');
        new _docprovider_awareness__WEBPACK_IMPORTED_MODULE_14__.WebSocketAwarenessProvider({
            url: url,
            roomID: 'JupyterLab:globalAwareness',
            awareness: awareness,
            user: user
        });
        state.changed.connect(async () => {
            var _a, _b;
            const data = await state.toJSON();
            const current = ((_b = (_a = data['layout-restorer:data']) === null || _a === void 0 ? void 0 : _a.main) === null || _b === void 0 ? void 0 : _b.current) || '';
            // For example matches `notebook:Untitled.ipynb` or `editor:untitled.txt`,
            // but not when in launcher or terminal.
            if (current.match(/^\w+:.+/)) {
                awareness.setLocalStateField('current', current);
            }
            else {
                awareness.setLocalStateField('current', null);
            }
        });
        return awareness;
    }
};
class AwarenessExecutionIndicatorIcon {
    createNew(panel) {
        const item = new _executionindicator__WEBPACK_IMPORTED_MODULE_15__.AwarenessExecutionIndicator();
        const nb = panel.content;
        item.model.attachNotebook({ content: nb });
        panel.toolbar.insertAfter('kernelName', 'awarenessExecutionProgress', item);
        return item;
    }
}
/**
 * A plugin that provides a execution indicator item to the status bar.
 */
const executionIndicator = {
    id: '@jupyter/rtc-core:awareness-execution-indicator',
    description: 'Adds a notebook execution status widget.',
    autoStart: true,
    requires: [_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__.INotebookTracker, _jupyterlab_application__WEBPACK_IMPORTED_MODULE_0__.ILabShell, _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4__.ITranslator, _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__.IToolbarWidgetRegistry],
    optional: [_jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_3__.IStatusBar, _jupyterlab_settingregistry__WEBPACK_IMPORTED_MODULE_1__.ISettingRegistry],
    activate: (app, notebookTracker, labShell, translator, statusBar, settingRegistry, toolbarRegistry) => {
        console.log('JupyterLab extension activated: Awareness Execution Indicator');
        app.docRegistry.addWidgetExtension('Notebook', new AwarenessExecutionIndicatorIcon());
    }
};
/**
 * A plugin that provides a kernel status item to the status bar.
 */
const kernelStatus = {
    id: '@jupyterlab/apputils-extension:awareness-kernel-status',
    description: 'Provides the kernel status indicator model.',
    autoStart: true,
    requires: [_jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_3__.IStatusBar],
    provides: _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__.IKernelStatusModel,
    optional: [_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__.ISessionContextDialogs, _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4__.ITranslator, _jupyterlab_application__WEBPACK_IMPORTED_MODULE_0__.ILabShell],
    activate: (app, statusBar, sessionDialogs_, translator_, labShell) => {
        console.log('JupyterLab extension activated: Awareness Kernel Status Indicator');
        const translator = translator_ !== null && translator_ !== void 0 ? translator_ : _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_4__.nullTranslator;
        const sessionDialogs = sessionDialogs_ !== null && sessionDialogs_ !== void 0 ? sessionDialogs_ : new _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_5__.SessionContextDialogs({ translator });
        // When the status item is clicked, launch the kernel
        // selection dialog for the current session.
        const changeKernel = async () => {
            if (!item.model.sessionContext) {
                return;
            }
            await sessionDialogs.selectKernel(item.model.sessionContext);
        };
        const changeKernelOnKeyDown = async (event) => {
            if (event.key === 'Enter' ||
                event.key === 'Spacebar' ||
                event.key === ' ') {
                event.preventDefault();
                event.stopPropagation();
                return changeKernel();
            }
        };
        // Create the status item.
        const item = new _kernelstatus__WEBPACK_IMPORTED_MODULE_16__.AwarenessKernelStatus({ onClick: changeKernel, onKeyDown: changeKernelOnKeyDown }, translator);
        const providers = new Set();
        const addSessionProvider = (provider) => {
            providers.add(provider);
            if (app.shell.currentWidget) {
                updateSession(app.shell, {
                    newValue: app.shell.currentWidget,
                    oldValue: null
                });
            }
        };
        function updateSession(shell, changes) {
            var _a;
            const { oldValue, newValue } = changes;
            // Clean up after the old value if it exists,
            // listen for changes to the title of the activity
            if (oldValue) {
                oldValue.title.changed.disconnect(onTitleChanged);
            }
            item.model.attachDocument(newValue);
            item.model.sessionContext =
                (_a = [...providers]
                    .map(provider => provider(changes.newValue))
                    .filter(session => session !== null)[0]) !== null && _a !== void 0 ? _a : null;
            if (newValue && item.model.sessionContext) {
                onTitleChanged(newValue.title);
                newValue.title.changed.connect(onTitleChanged);
            }
        }
        // When the title of the active widget changes, update the label
        // of the hover text.
        const onTitleChanged = (title) => {
            item.model.activityName = title.label;
        };
        if (labShell) {
            labShell.currentChanged.connect(updateSession);
        }
        statusBar.registerStatusItem(kernelStatus.id, {
            priority: 1,
            item,
            align: 'left',
            rank: 1,
            isActive: () => true
        });
        return { addSessionProvider };
    }
};
/**
 * The notebook cell factory provider.
 */
const factory = {
    id: '@jupyter/rtc-core/notebook-extension:factory',
    description: 'Provides the notebook cell factory.',
    provides: _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_2__.NotebookPanel.IContentFactory,
    requires: [_jupyterlab_codeeditor__WEBPACK_IMPORTED_MODULE_6__.IEditorServices],
    autoStart: true,
    activate: (app, editorServices) => {
        const editorFactory = editorServices.factoryService.newInlineEditor;
        return new _notebook__WEBPACK_IMPORTED_MODULE_17__.RtcNotebookContentFactory({ editorFactory });
    }
};
const plugins = [
    _docprovider__WEBPACK_IMPORTED_MODULE_18__.rtcContentProvider,
    _docprovider__WEBPACK_IMPORTED_MODULE_18__.yfile,
    _docprovider__WEBPACK_IMPORTED_MODULE_18__.ynotebook,
    _docprovider__WEBPACK_IMPORTED_MODULE_18__.logger,
    rtcGlobalAwarenessPlugin,
    plugin,
    executionIndicator,
    kernelStatus,
    factory
];
/* harmony default export */ const __WEBPACK_DEFAULT_EXPORT__ = (plugins);


/***/ }),

/***/ "./lib/kernelstatus.js":
/*!*****************************!*\
  !*** ./lib/kernelstatus.js ***!
  \*****************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   AwarenessKernelStatus: () => (/* binding */ AwarenessKernelStatus)
/* harmony export */ });
/* harmony import */ var _jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/statusbar */ "webpack/sharing/consume/default/@jupyterlab/statusbar");
/* harmony import */ var _jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/translation */ "webpack/sharing/consume/default/@jupyterlab/translation");
/* harmony import */ var _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyterlab/ui-components */ "webpack/sharing/consume/default/@jupyterlab/ui-components");
/* harmony import */ var _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! react */ "webpack/sharing/consume/default/react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_3__);
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! @jupyterlab/apputils */ "webpack/sharing/consume/default/@jupyterlab/apputils");
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_4___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_4__);
// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.





/**
 * A pure functional component for rendering kernel status.
 */
function KernelStatusComponent(props) {
    const translator = props.translator || _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__.nullTranslator;
    const trans = translator.load('jupyterlab');
    let statusText = '';
    if (props.status) {
        statusText = ` | ${props.status}`;
    }
    return (react__WEBPACK_IMPORTED_MODULE_3___default().createElement(_jupyterlab_statusbar__WEBPACK_IMPORTED_MODULE_0__.TextItem, { onClick: props.handleClick, onKeyDown: props.handleKeyDown, source: `${props.kernelName}${statusText}`, title: trans.__('Change kernel for %1', props.activityName), tabIndex: 0 }));
}
class AwarenessKernelStatus extends _jupyterlab_ui_components__WEBPACK_IMPORTED_MODULE_2__.VDomRenderer {
    /**
     * Construct the kernel status widget.
     */
    constructor(opts, translator) {
        super(new AwarenessKernelStatus.Model(translator));
        this.translator = translator || _jupyterlab_translation__WEBPACK_IMPORTED_MODULE_1__.nullTranslator;
        this._handleClick = opts.onClick;
        this._handleKeyDown = opts.onKeyDown;
        this.addClass('jp-mod-highlighted');
    }
    /**
     * Render the kernel status item.
     */
    render() {
        if (this.model === null) {
            return null;
        }
        else {
            return (react__WEBPACK_IMPORTED_MODULE_3___default().createElement(KernelStatusComponent, { status: this.model.status, kernelName: this.model.kernelName, activityName: this.model.activityName, handleClick: this._handleClick, handleKeyDown: this._handleKeyDown, translator: this.translator }));
        }
    }
}
(function (AwarenessKernelStatus) {
    class Model extends _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_4__.KernelStatus.Model {
        attachDocument(widget) {
            var _a;
            if (!widget) {
                return;
            }
            const panel = widget;
            const stateChanged = () => {
                var _a;
                if (this) {
                    const awarenessStates = (_a = panel === null || panel === void 0 ? void 0 : panel.model) === null || _a === void 0 ? void 0 : _a.sharedModel.awareness.getStates();
                    if (awarenessStates) {
                        for (const [_, clientState] of awarenessStates) {
                            if ('kernel' in clientState) {
                                this._kernelStatus =
                                    clientState['kernel']['execution_state'];
                                this.stateChanged.emit(void 0);
                                return;
                            }
                        }
                    }
                }
            };
            (_a = panel.model) === null || _a === void 0 ? void 0 : _a.sharedModel.awareness.on('change', stateChanged);
        }
        set sessionContext(sessionContext) {
            var _a;
            const oldState = this._getAllState();
            this._sessionContext = sessionContext;
            this._kernelName =
                (_a = sessionContext === null || sessionContext === void 0 ? void 0 : sessionContext.kernelDisplayName) !== null && _a !== void 0 ? _a : this._trans.__('No Kernel');
            this._triggerChange(oldState, this._getAllState());
            sessionContext === null || sessionContext === void 0 ? void 0 : sessionContext.kernelChanged.connect(this._onKernelDisplayNameChanged, this);
        }
        /**
         * React to changes in the kernel.
         */
        _onKernelDisplayNameChanged(_sessionContext, change) {
            const oldState = this._getAllState();
            // sync setting of status and display name
            this._kernelName = _sessionContext.kernelDisplayName;
            this._triggerChange(oldState, this._getAllState());
        }
    }
    AwarenessKernelStatus.Model = Model;
})(AwarenessKernelStatus || (AwarenessKernelStatus = {}));


/***/ }),

/***/ "./lib/notebook.js":
/*!*************************!*\
  !*** ./lib/notebook.js ***!
  \*************************/
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   RtcNotebookContentFactory: () => (/* binding */ RtcNotebookContentFactory)
/* harmony export */ });
/* harmony import */ var _jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/cells */ "webpack/sharing/consume/default/@jupyterlab/cells");
/* harmony import */ var _jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @jupyterlab/notebook */ "webpack/sharing/consume/default/@jupyterlab/notebook");
/* harmony import */ var _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1__);
/* harmony import */ var _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @jupyter/ydoc */ "webpack/sharing/consume/default/@jupyter/ydoc");
/* harmony import */ var _jupyter_ydoc__WEBPACK_IMPORTED_MODULE_2___default = /*#__PURE__*/__webpack_require__.n(_jupyter_ydoc__WEBPACK_IMPORTED_MODULE_2__);
/* harmony import */ var _jupyterlab_outputarea__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @jupyterlab/outputarea */ "webpack/sharing/consume/default/@jupyterlab/outputarea");
/* harmony import */ var _jupyterlab_outputarea__WEBPACK_IMPORTED_MODULE_3___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_outputarea__WEBPACK_IMPORTED_MODULE_3__);
/* harmony import */ var _handler__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ./handler */ "./lib/handler.js");





const globalModelDBMutex = (0,_jupyter_ydoc__WEBPACK_IMPORTED_MODULE_2__.createMutex)();
_jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__.CodeCellModel.prototype._onSharedModelChanged = function (slot, change) {
    if (change.streamOutputChange) {
        globalModelDBMutex(() => {
            for (const streamOutputChange of change.streamOutputChange) {
                if ('delete' in streamOutputChange) {
                    this._outputs.removeStreamOutput(streamOutputChange.delete);
                }
                if ('insert' in streamOutputChange) {
                    this._outputs.appendStreamOutput(streamOutputChange.insert.toString());
                }
            }
        });
    }
    if (change.outputsChange) {
        globalModelDBMutex(() => {
            var _a;
            let retain = 0;
            for (const outputsChange of change.outputsChange) {
                if ('retain' in outputsChange) {
                    retain += outputsChange.retain;
                }
                if ('delete' in outputsChange) {
                    for (let i = 0; i < outputsChange.delete; i++) {
                        this._outputs.remove(retain);
                    }
                }
                if ('insert' in outputsChange) {
                    // Inserting an output always results in appending it.
                    for (const output of outputsChange.insert) {
                        // For compatibility with older ydoc where a plain object,
                        // (rather than a Map instance) could be provided.
                        // In a future major release the use of Map will be required.
                        if ('toJSON' in output) {
                            const json = output.toJSON();
                            if ((_a = json.metadata) === null || _a === void 0 ? void 0 : _a.url) {
                                // fetch the output from ouputs service
                                (0,_handler__WEBPACK_IMPORTED_MODULE_4__.requestAPI)(json.metadata.url).then(data => {
                                    this._outputs.add(data);
                                });
                            }
                            else {
                                this._outputs.add(json);
                            }
                        }
                        else {
                            this._outputs.add(output);
                        }
                    }
                }
            }
        });
    }
    if (change.executionCountChange) {
        if (change.executionCountChange.newValue &&
            (this.isDirty || !change.executionCountChange.oldValue)) {
            this._setDirty(false);
        }
        this.stateChanged.emit({
            name: 'executionCount',
            oldValue: change.executionCountChange.oldValue,
            newValue: change.executionCountChange.newValue
        });
    }
    if (change.executionStateChange) {
        this.stateChanged.emit({
            name: 'executionState',
            oldValue: change.executionStateChange.oldValue,
            newValue: change.executionStateChange.newValue
        });
    }
    if (change.sourceChange && this.executionCount !== null) {
        this._setDirty(this._executedCode !== this.sharedModel.getSource().trim());
    }
};
_jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__.CodeCellModel.prototype.onOutputsChange = function (sender, event) {
    // no-op
};
/* An OutputAreaModel that loads outputs from outputs service */
class RtcOutputAreaModel extends _jupyterlab_outputarea__WEBPACK_IMPORTED_MODULE_3__.OutputAreaModel {
    constructor(options = {}) {
        super({ ...options, values: [] }); // Don't pass values to OutputAreaModel
        if (options.values) {
            // Create an array to store promises for each value
            const valuePromises = options.values.map(value => {
                var _a;
                console.debug('output #${index}, value: ${value}');
                if ((_a = value.metadata) === null || _a === void 0 ? void 0 : _a.url) {
                    return (0,_handler__WEBPACK_IMPORTED_MODULE_4__.requestAPI)(value.metadata.url)
                        .then(data => {
                        return data;
                    })
                        .catch(error => {
                        console.error('Error fetching output:', error);
                        return null;
                    });
                }
                else {
                    // For values without url, return immediately with original value
                    return Promise.resolve(value);
                }
            });
            // Wait for all promises to resolve and add values in original order
            Promise.all(valuePromises).then(results => {
                console.log('After fetching from outputs service:');
                // Add each value in order
                results.forEach((data, index) => {
                    console.debug('output #${index}, data: ${data}');
                    if (data && !this.isDisposed) {
                        const index = this._add(data) - 1;
                        const item = this.list.get(index);
                        item.changed.connect(this._onGenericChange, this);
                    }
                });
            });
        }
    }
}
_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1__.NotebookModel.prototype._onStateChanged = function (sender, changes) {
    if (changes.stateChange) {
        changes.stateChange.forEach(value => {
            if (value.name === 'dirty') {
                // Setting `dirty` will trigger the state change.
                // We always set `dirty` because the shared model state
                // and the local attribute are synchronized one way shared model -> _dirty
                this.dirty = value.newValue;
            }
            else if (value.oldValue !== value.newValue) {
                this.triggerStateChange({
                    newValue: undefined,
                    oldValue: undefined,
                    ...value
                });
            }
        });
    }
};
Object.defineProperty(_jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1__.NotebookModel.prototype, "dirty", {
    set: function (newValue) {
        console.trace("Calling set dirty with value: ", newValue);
        const oldValue = this._dirty;
        if (newValue === oldValue) {
            return;
        }
        this._dirty = newValue;
        this.triggerStateChange({
            name: 'dirty',
            oldValue,
            newValue
        });
    },
    get: function () {
        return this._readOnly;
    },
    enumerable: true,
    configurable: true
});
_jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__.CodeCellModel.ContentFactory.prototype.createOutputArea = function (options) {
    return new RtcOutputAreaModel(options);
};
class RtcNotebookContentFactory extends _jupyterlab_notebook__WEBPACK_IMPORTED_MODULE_1__.NotebookPanel.ContentFactory {
    createCodeCell(options) {
        return new _jupyterlab_cells__WEBPACK_IMPORTED_MODULE_0__.CodeCell(options).initializeState();
    }
}


/***/ })

}]);
//# sourceMappingURL=lib_index_js.cc898f1e555e467c62ea.js.map