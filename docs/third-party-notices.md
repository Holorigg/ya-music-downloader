# Сторонние компоненты

[MIT](../LICENSE) относится к собственному коду проекта. Сторонние компоненты
и материалы распространяются по своим лицензиям.

## Windows

Python-пакеты устанавливаются из PyPI; их wheels и виртуальное окружение
не входят в репозиторий.

| Компонент | Версия | Лицензия и источник |
|---|---|---|
| PySide6-Essentials, shiboken6 / Qt for Python | 6.12.0 | LGPLv3, GPLv3 или коммерческая, в зависимости от компонента и использования: [Qt for Python](https://doc.qt.io/qtforpython-6/), [Qt licensing](https://doc.qt.io/qt-6/licensing.html) |
| Mutagen | 1.47.0 | GPL-2.0-or-later: [COPYING](https://github.com/quodlibet/mutagen/blob/release-1.47.0/COPYING) |
| Requests | 2.34.2 | Apache-2.0: [LICENSE](https://github.com/psf/requests/blob/v2.34.2/LICENSE) |
| certifi | 2026.7.22 | MPL-2.0: [метаданные релиза](https://pypi.org/pypi/certifi/2026.7.22/json) |
| charset-normalizer | 3.5.2 | MIT: [метаданные релиза](https://pypi.org/pypi/charset-normalizer/3.5.2/json) |
| idna | 3.20 | BSD-3-Clause: [метаданные релиза](https://pypi.org/pypi/idna/3.20/json) |
| urllib3 | 2.8.0 | MIT: [метаданные релиза](https://pypi.org/pypi/urllib3/2.8.0/json) |

FFmpeg и FFprobe устанавливаются отдельно. Лицензия зависит от конфигурации
конкретной сборки: [FFmpeg License](https://ffmpeg.org/legal.html).
Готовые Windows-бинарники требуют отдельного комплекта уведомлений и
выполнения условий используемых зависимостей, включая Mutagen и Qt.

## Android

Зависимости загружаются из Google Maven и Maven Central.

| Компонент | Версия | Лицензия и источник |
|---|---|---|
| Material Components for Android | 1.14.0 | Apache-2.0: [LICENSE](https://github.com/material-components/material-components-android/blob/1.14.0/LICENSE) |
| AndroidX AppCompat | 1.7.1 | Apache-2.0: [LICENSE AndroidX](https://github.com/androidx/androidx/blob/androidx-main/LICENSE.txt) |
| AndroidX RecyclerView | 1.4.0 | Apache-2.0: [LICENSE AndroidX](https://github.com/androidx/androidx/blob/androidx-main/LICENSE.txt) |
| JUnit, только тесты | 4.13.2 | EPL-1.0: [LICENSE](https://github.com/junit-team/junit4/blob/r4.13.2/LICENSE-junit.txt) |
| Robolectric, только тесты | 4.16 | MIT; отдельные файлы Apache-2.0: [LICENSE](https://github.com/robolectric/robolectric/blob/robolectric-4.16/LICENSE) |

Gradle Wrapper 8.13 включён в исходники, в том числе `gradle-wrapper.jar`,
под Apache-2.0: [источник](https://github.com/gradle/gradle/tree/v8.13.0),
[копия лицензии](../third_party/gradle-APACHE-2.0.txt).
JDK, Android SDK, загруженный Gradle и кеши зависимостей не включены.

## Иконки и справочные материалы

SVG Google Material Icons скопированы под Apache-2.0:
[источник](https://github.com/google/material-design-icons),
[копия лицензии](../third_party/material-icons-APACHE-2.0.txt).
Собственная иконка приложения создана с GPT Image. Демообложки для README
рисуются кодом проекта; пользовательские обложки и музыкальные файлы не включены.

Форматы и публичные параметры API сверялись с
[MarshalX/yandex-music-api, ревизия 9ca132e5](https://github.com/MarshalX/yandex-music-api/tree/9ca132e5c18a72aab779c1fc68c169380a9357d0).
В этой ревизии библиотека опубликована под
[LGPL-3.0](https://github.com/MarshalX/yandex-music-api/blob/9ca132e5c18a72aab779c1fc68c169380a9357d0/LICENSE).
Она не импортируется, не исполняется и не включена в проект.

[llistochek/yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader)
упомянут как близкий проект сообщества; его код здесь не используется.
