# Разработка

Среда и сборка: [Windows](../desktop/README.md) · [Android](../android/README.md).

## Проверки

Windows, из `desktop` после установки зависимостей и FFmpeg:

```powershell
.\.venv\Scripts\python.exe run_checks.py
```

Команда запускает проверки в отдельном временном профиле. Аудио генерирует
FFmpeg; обложки, тексты и ответы API синтетические. Аккаунт и сеть не нужны.

Android, из `android`:

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintRelease
```

Robolectric проверяет логику и отрисовывает настоящие Android Views без
эмулятора. SAF, Keystore, уведомления и поведение фоновых задач дополнительно
проверяются на устройстве. Debug APK имеет суффикс пакета `.debug` и не
заменяет основную установку.

Полный JVM-прогон в CI выполняется на Windows. На Ubuntu обнаружен сбой
инициализации нативного runtime Robolectric; тесты отрисовки остаются
включены в режиме `NATIVE`. Прохождение этого набора на Linux пока не подтверждено.

## Сборки Windows

Используй Windows x64 и Python 3.12. Установи зависимости приложения и
`desktop/build-requirements.txt` в отдельное виртуальное окружение.
В `desktop/tools` положи FFmpeg, FFprobe и DLL выбранной LGPL shared сборки;
в `desktop/packaging/licenses` — её лицензию, уведомления зависимостей,
исходники и инструкции их получения. Эти каталоги исключены из Git.
Состав готового комплекта описан в его `licenses/SOURCES.md`.

```powershell
python tools/build_windows.py --mode both
```

Результаты: `desktop/dist/onedir/MyMusic/MyMusic.exe` с каталогом `_internal`
и самостоятельный `desktop/dist/onefile/MyMusic.exe`. Для portable ZIP
упаковывай весь каталог `MyMusic`, включая `_internal`.

Проверь оба EXE, в том числе worker и инструменты, без настоящего аккаунта:

```powershell
.\desktop\dist\onedir\MyMusic\MyMusic.exe --bundle-self-test "$env:TEMP\music-onedir-check.json"
.\desktop\dist\onefile\MyMusic.exe --bundle-self-test "$env:TEMP\music-onefile-check.json"
```

Диагностика создаёт временный профиль, использует синтетическое аудио и
записывает JSON-отчёт. Запуск без авторизации не делает сетевых запросов.

Перед коммитом, из корня репозитория:

```powershell
git add .
python tools/check_public_tree.py
python tools/check_versions.py
git diff --cached --check
```

Сканер проверяет выбранные для Git файлы. Это дополнительная проверка;
просмотри сам diff перед публикацией.

## Отдельный профиль

Для запуска интерфейса во время разработки задай новый `MUSIC_DATA_DIR`:

```powershell
$env:MUSIC_DATA_DIR = Join-Path $env:TEMP ('YaMusicDownloader-dev-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe app.py
```

На Android выбери другую папку музыки в dev-версии. Проверки не должны
использовать реальный токен, базу или музыкальные файлы пользователя.

## Скриншоты

Windows: `.\.venv\Scripts\python.exe -B render_demo.py` из `desktop`.
Все данные создаются во временной папке; сетевые запросы заблокированы.
Скриншоты сохраняются в `docs/screenshots`.

Android: тесты `RenderChecks` создают демоэкраны в `android/design/screens`.
Для README выбраны `library-dark.png` и `library-light.png`; их копии находятся
в `docs/screenshots`. Они не включают статусную панель и оболочку устройства.

## Изменения

- Windows и Android выпускаются с одним номером версии. Обновляй `VERSION`
  в `desktop/app.py` и `versionName` в `android/android-app/build.gradle`
  вместе; для Android также увеличивай `versionCode`. Тег релиза — `vX.Y.Z`.
  Перед выпуском выполни `python tools/check_versions.py --tag vX.Y.Z`.
- Сохраняй файлы при скрытии или очистке архива, а также проверку целостности
  и защиту от перезаписи посторонних файлов.
- Не отправляй OAuth-токен серверам аудио, обложек или текстов.
- Не добавляй токены, базы, логи, загруженную музыку, ключи подписи и частные
  скриншоты. SDK, виртуальные окружения и сборки исключены из Git.
- Новые сторонние материалы сопровождай источником и лицензией в
  [уведомлениях](third-party-notices.md).

В описании изменения укажи наблюдаемое поведение, выполненные проверки и
оставшиеся ограничения. Сетевые проверки с аккаунтом описывай отдельно от
автономных тестов.
