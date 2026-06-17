# Changelog

<!-- <START NEW CHANGELOG ENTRY> -->

## 0.3.0b0

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.4...8208a87db3599e2995fb9946d941a6ba0b6a0cd2))

### Enhancements made

- Remove YRoom restart logic and adopt upstream docprovider [#251](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/251) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))
- [Feature] Server-side cell execution via REST API [#248](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/248) ([@Zsailer](https://github.com/Zsailer), [@davidbrochart](https://github.com/davidbrochart), [@dlqqq](https://github.com/dlqqq), [@krassowski](https://github.com/krassowski))
- Disable outputs service by default [#247](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/247) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-06-11&to=2026-06-17&type=c))

@davidbrochart ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adavidbrochart+updated%3A2026-06-11..2026-06-17&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-06-11..2026-06-17&type=Issues)) | @krassowski ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Akrassowski+updated%3A2026-06-11..2026-06-17&type=Issues)) | @Zsailer ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2026-06-11..2026-06-17&type=Issues))

<!-- <END NEW CHANGELOG ENTRY> -->

## 0.2.4

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.3...39c6f391b80ce14451861c1312722cba48e9c857))

### Bugs fixed

- Support jupyter-collaboration-ui 2.4.0 [#249](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/249) ([@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-06-10&to=2026-06-11&type=c))

@dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-06-10..2026-06-11&type=Issues))

## 0.2.3

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.2...22ad4489c33991b6abfcb7a7d2001635e4c25405))

### Bugs fixed

- Bump @playwright/test to ^1.60.0 to fix CI stalling [#245](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/245) ([@dlqqq](https://github.com/dlqqq))
- fix: restore kernel.last_activity updates for idle monitoring [#240](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/240) ([@joshuatowner](https://github.com/joshuatowner), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-05-12&to=2026-06-10&type=c))

@dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-05-12..2026-06-10&type=Issues)) | @joshuatowner ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Ajoshuatowner+updated%3A2026-05-12..2026-06-10&type=Issues))

## 0.2.2

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.1...e75961d30c314752555950d5161e56b2bebce156))

### Bugs fixed

- Require `jupyter-collaboration-ui<2.4.0` [#236](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/236) ([@snoopuppy582](https://github.com/snoopuppy582), [@dlqqq](https://github.com/dlqqq))
- Fix kernel consoles [#230](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/230) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))
- Fix output loss from clear_output race condition [#222](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/222) ([@Zsailer](https://github.com/Zsailer), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-05-05&to=2026-05-12&type=c))

@dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-05-05..2026-05-12&type=Issues)) | @snoopuppy582 ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Asnoopuppy582+updated%3A2026-05-05..2026-05-12&type=Issues)) | @Zsailer ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2026-05-05..2026-05-12&type=Issues))

## 0.2.1

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.0...3bf3e8a820624e09e7cc4884d6dc07deb715f0d5))

### Enhancements made

- ci: add dedicated unit tests workflow [#228](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/228) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))
- fix: batched catchup in YRoomUpdateChannel.resume() [#227](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/227) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))

### Bugs fixed

- Decouple room GC from kernel shutdown [#229](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/229) ([@Zsailer](https://github.com/Zsailer), [@dlqqq](https://github.com/dlqqq))
- Allow GC to free notebook rooms with unknown execution state [#224](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/224) ([@Zsailer](https://github.com/Zsailer), [@dlqqq](https://github.com/dlqqq))
- fix: batched catchup in YRoomUpdateBuffer.resume() [#218](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/218) ([@xrl](https://github.com/xrl), [@claude](https://github.com/claude), [@dlqqq](https://github.com/dlqqq))
- fix: bounds-check output index before array assignment (#216) [#217](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/217) ([@j1wonpark](https://github.com/j1wonpark), [@3coins](https://github.com/3coins), [@dlqqq](https://github.com/dlqqq))

### Maintenance and upkeep improvements

- test: stress tests for sync handshake under concurrent mutations [#219](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/219) ([@xrl](https://github.com/xrl), [@claude](https://github.com/claude), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-04-21&to=2026-05-05&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2026-04-21..2026-05-05&type=Issues)) | @claude ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aclaude+updated%3A2026-04-21..2026-05-05&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-04-21..2026-05-05&type=Issues)) | @j1wonpark ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aj1wonpark+updated%3A2026-04-21..2026-05-05&type=Issues)) | @xrl ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Axrl+updated%3A2026-04-21..2026-05-05&type=Issues)) | @Zsailer ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2026-04-21..2026-05-05&type=Issues))

## 0.2.0

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.0a1))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-04-11&to=2026-04-21&type=c))

## 0.2.0a1

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.2.0a0...740eac764b7f0545bbb273b6dc61301c6fa2012d))

### Bugs fixed

- Fix content duplication on reconnection [#215](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/215) ([@dlqqq](https://github.com/dlqqq), [@3coins](https://github.com/3coins))
- Wait few seconds before GC run [#212](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/212) ([@dlqqq](https://github.com/dlqqq), [@3coins](https://github.com/3coins))

### Maintenance and upkeep improvements

- fix: remove leftover example endpoint logging [#213](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/213) ([@ObservedObserver](https://github.com/ObservedObserver), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-04-07&to=2026-04-11&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2026-04-07..2026-04-11&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-04-07..2026-04-11&type=Issues)) | @ObservedObserver ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AObservedObserver+updated%3A2026-04-07..2026-04-11&type=Issues))

## 0.2.0a0

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.2...7df9c4d5e0b90628859fa1aded663b5dbed2ae2c))

### Enhancements made

- Free memory in document rooms automatically [#193](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/193) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))

### Bugs fixed

- Added yroom reconnect [#209](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/209) ([@3coins](https://github.com/3coins), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-03-30&to=2026-04-07&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2026-03-30..2026-04-07&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-03-30..2026-04-07&type=Issues)) | @Zsailer ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2026-03-30..2026-04-07&type=Issues))

## 0.1.2

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.1...3ae9d06e5a829b36010be9239f184ff97d001fa9))

### Bugs fixed

- Clears outputs on each execute [#207](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/207) ([@3coins](https://github.com/3coins), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-03-24&to=2026-03-30&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2026-03-24..2026-03-30&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-03-24..2026-03-30&type=Issues))

## 0.1.1

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.0...2c8a4de745d52d4eee13d2af18686d6ca1591f17))

### Bugs fixed

- Fix cell duplication on out-of-band file changes by reloading file content in-place [#202](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/202) ([@sathishlxg](https://github.com/sathishlxg), [@3coins](https://github.com/3coins), [@Zsailer](https://github.com/Zsailer), [@dlqqq](https://github.com/dlqqq))
- Add ping/pong keepalive to YRoomWebsocket [#201](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/201) ([@dlqqq](https://github.com/dlqqq), [@Zsailer](https://github.com/Zsailer))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/use/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2026-01-15&to=2026-03-24&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2026-01-15..2026-03-24&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2026-01-15..2026-03-24&type=Issues)) | @sathishlxg ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Asathishlxg+updated%3A2026-01-15..2026-03-24&type=Issues)) | @Zsailer ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2026-01-15..2026-03-24&type=Issues))

## 0.1.0

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.0a9...a65fd2129eca2e844fa02590020af8a2f7159fd3))

### Enhancements made

- Disable OOB change notification [#187](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/187) ([@dlqqq](https://github.com/dlqqq), [@ellisonbg](https://github.com/ellisonbg))

### Bugs fixed

- Remove save toolbar buttons [#180](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/180) ([@nakul-py](https://github.com/nakul-py), [@dlqqq](https://github.com/dlqqq))

### Maintenance and upkeep improvements

- Update verbose logs to debug level [#181](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/181) ([@3coins](https://github.com/3coins), [@dlqqq](https://github.com/dlqqq))

### Other merged PRs

- Fix metadata links [#184](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/184) ([@ktaletsk](https://github.com/ktaletsk), [@dlqqq](https://github.com/dlqqq))

### Contributors to this release

The following people contributed discussions, new ideas, code and documentation contributions, and review.
See [our definition of contributors](https://github-activity.readthedocs.io/en/latest/#how-does-this-tool-define-contributions-in-the-reports).

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2025-11-18&to=2026-01-15&type=c))

@3coins ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2025-11-18..2026-01-15&type=Issues)) | @dlqqq ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2025-11-18..2026-01-15&type=Issues)) | @ellisonbg ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aellisonbg+updated%3A2025-11-18..2026-01-15&type=Issues)) | @ktaletsk ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aktaletsk+updated%3A2025-11-18..2026-01-15&type=Issues)) | @nakul-py ([activity](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Anakul-py+updated%3A2025-11-18..2026-01-15&type=Issues))

## 0.1.0a9

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.0a8...dccb851a90d057da08c55a9c7e4d4da77bb80c8b))

### Enhancements made

- Remove excessive sync message logging [#172](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/172) ([@Zsailer](https://github.com/Zsailer))

### Bugs fixed

- Replace CRLF with LF when loading file [#177](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/177) ([@dlqqq](https://github.com/dlqqq))
- Fixes server error when deleted rooms are saved at shutdown [#175](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/175) ([@3coins](https://github.com/3coins))

### Documentation improvements

- docs: fix small typo [#173](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/173) ([@rgbkrk](https://github.com/rgbkrk))

### Contributors to this release

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2025-10-23&to=2025-11-18&type=c))

[@3coins](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2025-10-23..2025-11-18&type=Issues) | [@dlqqq](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2025-10-23..2025-11-18&type=Issues) | [@rgbkrk](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Argbkrk+updated%3A2025-10-23..2025-11-18&type=Issues) | [@Zsailer](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3AZsailer+updated%3A2025-10-23..2025-11-18&type=Issues)

## 0.1.0a8

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.0a7...dcf8a50078d525356737c69a94ca919281c2e379))

### Enhancements made

- Cleanup and add validation to new adaptive saving strategy [#169](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/169) ([@dlqqq](https://github.com/dlqqq))
- Refactor OutputsManager to align with default Jupyter behavior [#163](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/163) ([@ellisonbg](https://github.com/ellisonbg))

### Contributors to this release

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2025-10-22&to=2025-10-23&type=c))

[@3coins](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2025-10-22..2025-10-23&type=Issues) | [@dlqqq](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2025-10-22..2025-10-23&type=Issues) | [@ellisonbg](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aellisonbg+updated%3A2025-10-22..2025-10-23&type=Issues)

## 0.1.0a7

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/v0.1.0a6...a1dbf46fc33e3e02fe475b3f197d1e17501d3374))

### Enhancements made

- Rename NPM package [#166](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/166) ([@dlqqq](https://github.com/dlqqq))
- Handle YChat document resets when `jupyterlab_chat` is installed [#161](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/161) ([@dlqqq](https://github.com/dlqqq))

### Bugs fixed

- Track if files are writable and disable saving if they are not. [#164](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/164) ([@ellisonbg](https://github.com/ellisonbg))

### Contributors to this release

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2025-10-14&to=2025-10-22&type=c))

[@3coins](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2025-10-14..2025-10-22&type=Issues) | [@dlqqq](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2025-10-14..2025-10-22&type=Issues) | [@ellisonbg](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aellisonbg+updated%3A2025-10-14..2025-10-22&type=Issues)

## 0.1.0a6

([Full Changelog](https://github.com/jupyter-ai-contrib/jupyter-server-documents/compare/10c176a76ac7595a299d4ccb4ccfb57c283c2182...bc6b60d58f569e77ab828ffe3cccff2d09a83675))

### Enhancements made

- Add optional `on_reset` argument to `YRoom` get methods [#152](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/152) ([@dlqqq](https://github.com/dlqqq))

### Bugs fixed

- Fixing lint error [#159](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/159) ([@3coins](https://github.com/3coins))
- Fix real-time output clearing for collaborative editing [#150](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/150) ([@ellisonbg](https://github.com/ellisonbg))

### Documentation improvements

- Add `CLAUDE.md` and `AGENTS.md` [#154](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/154) ([@dlqqq](https://github.com/dlqqq))

### Other merged PRs

- Increase stream limit to 200 [#149](https://github.com/jupyter-ai-contrib/jupyter-server-documents/pull/149) ([@ellisonbg](https://github.com/ellisonbg))

### Contributors to this release

([GitHub contributors page for this release](https://github.com/jupyter-ai-contrib/jupyter-server-documents/graphs/contributors?from=2025-07-25&to=2025-10-14&type=c))

[@3coins](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3A3coins+updated%3A2025-07-25..2025-10-14&type=Issues) | [@dlqqq](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Adlqqq+updated%3A2025-07-25..2025-10-14&type=Issues) | [@ellisonbg](https://github.com/search?q=repo%3Ajupyter-ai-contrib%2Fjupyter-server-documents+involves%3Aellisonbg+updated%3A2025-07-25..2025-10-14&type=Issues)
