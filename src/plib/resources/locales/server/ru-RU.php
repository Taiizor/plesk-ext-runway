<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Russian translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../ru-RU.php; the frontend strings live in ../app/ru-RU.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Устанавливайте наборы инструментов и запускайте приложения как службы без Docker.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Соберите и запустите на этом домене приложение на Go, Rust, Bun, Java, .NET, Python, Ruby или PHP либо готовый исполняемый файл.',
    'permissionName' => 'Управление приложениями Runway',
    'permissionDescription' => 'Позволяет клиенту собирать и запускать приложения как фоновые службы с помощью Runway.',

    // Errors
    'errorHelperFailed' => 'Сбой привилегированного помощника: %%details%%',
    'errorAccessDenied' => 'Доступ запрещён.',
    'errorNoDomain' => 'Домен не найден.',
    'errorNoHosting' => 'У домена нет веб-хостинга.',
    'errorNotConfigured' => 'Приложение ещё не настроено. Сначала сохраните настройки.',
    'errorInvalidOperation' => 'Недопустимая операция.',
    'errorInvalidValue' => 'Недопустимое значение.',
    'errorPostRequired' => 'Это действие требует запроса POST.',
    'errorInternal' => 'Произошла внутренняя ошибка. Подробности в журнале панели Plesk.',
    'errorRuntime' => 'Выберите допустимую среду выполнения.',
    'errorToolchain' => 'Выберите допустимую версию набора инструментов.',
    'errorAppRoot' => 'Корневой каталог приложения должен быть путём внутри подписки (буквы, цифры и . _ - @ + /) без сегментов «.» и «..».',
    'errorBuildCmd' => 'Команда сборки слишком длинная или содержит управляющие символы.',
    'errorStartCmd' => 'Команда запуска должна быть одной строкой без управляющих символов (не более 1000 символов).',
    'errorStartCmdEmpty' => 'Для включения приложения требуется команда запуска.',
    'errorLimit' => '%%name%% должен быть целым числом в допустимом диапазоне.',
    'errorEnvLine' => 'Строка %%line%%: используйте формат КЛЮЧ=значение.',
    'errorEnvKey' => 'Строка %%line%%: «%%key%%» не является допустимым именем переменной.',
    'errorEnvReserved' => 'Переменная %%key%% управляется Runway и не может быть задана.',
    'errorEnvLoader' => 'Переменную %%key%% нельзя задать здесь; укажите её в команде запуска (например, %%key%%=... ./app).',
    'errorEnvValue' => 'Значение %%key%% не должно содержать переводы строк или управляющие символы.',
    'errorEnvTooMany' => 'Слишком много переменных окружения (не более 200).',
    'errorListen' => 'Выберите допустимый режим прослушивания.',
    'errorMode' => 'Выберите допустимый режим приложения.',
    'errorMountPath' => 'Путь URL должен быть вида /api (буквы, цифры и . _ ~ -).',
    'errorStaticPaths' => 'Статические пути должны быть списком путей URL.',
    'errorStaticPath' => '«%%path%%» не является допустимым путём URL (пример: /assets).',
    'errorStaticPathsTooMany' => 'Допускается не более %%max%% статических путей.',
    'errorStaticPathsTooLong' => 'Статические пути в сумме слишком длинные (не более %%max%% символов).',
    'errorConfigTooLarge' => 'Настройки в сумме слишком длинные (%%length%% из %%max%% допустимых символов): сократите команды или пути.',
    'errorHealthPath' => 'Путь проверки работоспособности должен быть путём URL вида /healthz.',
    'errorPortRange' => 'Первый порт не может быть больше последнего.',
    'errorSettingRange' => 'Введите целое число от %%min%% до %%max%%.',
    'errorListenMode' => 'Фоновый процесс ничего не прослушивает: выберите режим прослушивания «Ничего» либо веб-режим с TCP-портом или Unix-сокетом.',
    'errorMountPathReserved' => '%%path%% используется Plesk (веб-статистика или проверка сертификатов) и не может быть проксирован.',
    'errorMaxApps' => 'В этой подписке уже достигнуто максимальное число включённых приложений (%%max%%).',
    'errorFetchUrl' => 'Введите URL вида https:// (не более 2048 символов, без пробелов).',
    'errorFetchHttps' => 'Скачивать можно только по URL https://.',
    'errorSampleNotEmpty' => 'Корневой каталог приложения не пуст. Подтвердите, что пример может перезаписать файлы. %%details%%',
    'errorSampleUnix' => 'Стандартный сервер PHP (php -S) не может прослушивать Unix-сокет: установите набор инструментов FrankenPHP или выберите TCP.',
    'errorFetchSha256' => 'Контрольная сумма SHA-256 должна состоять из 64 шестнадцатеричных символов.',
    'errorFetchFilename' => 'Имя файла может содержать только буквы, цифры и . _ + - (не более 128 символов).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Лимит памяти (МиБ)',
    'fieldCpuPercent' => 'Лимит ЦП (%)',
    'fieldTasks' => 'Лимит процессов / потоков',

    // Messages
    'messageSavedEnabled' => 'Настройки сохранены, приложение (пере)запускается.',
    'messageSavedBuilding' => 'Настройки сохранены. Приложение собирается и будет (пере)запущено после успешной сборки; следите за ходом в журнале «Сборка и развёртывание».',
    'messageSavedBuildNotStarted' => 'Настройки сохранены, но сборку не удалось запустить: %%details%%',
    'messageSavedDisabled' => 'Настройки сохранены. Приложение отключено.',
    'messageAction_start' => 'Приложение запускается.',
    'messageAction_stop' => 'Приложение остановлено. Оно останется остановленным, пока вы не запустите его снова.',
    'messageAction_restart' => 'Приложение перезапускается.',
    'messageDeployStarted' => 'Сборка запущена. Следите за ходом в журнале «Сборка и развёртывание».',
    'messageRemoved' => 'Приложение удалено.',
    'messageJobStarted' => 'Задача запущена. Ход её выполнения отображается ниже.',
    'messageToolchainRemoved' => 'Версия %%version%% удалена.',
    'messageSampleWritten' => 'Пример приложения записан (файлов: %%count%%), настройки обновлены.',
    'messageSampleWrittenOne' => 'Пример приложения записан (один файл), настройки обновлены.',
    'messageFetchStarted' => 'Скачивание начато. Следите за ходом в журнале «Сборка и развёртывание».',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Вывести список настроенных приложений и их состояние.',
    'cli.commands.status' => 'Показать состояние приложения домена: --status <домен>',
    'cli.commands.start' => 'Запустить приложение домена: --start <домен>',
    'cli.commands.stop' => 'Остановить приложение домена; оно останется остановленным (в том числе после перезагрузки или развёртывания) до --start или --restart: --stop <домен>',
    'cli.commands.restart' => 'Перезапустить приложение домена: --restart <домен>',
    'cli.commands.deploy' => 'Собрать и перезапустить приложение домена и дождаться результата (остановленное приложение собирается, но остаётся остановленным): --deploy <домен> [-no-wait]',
    'cli.commands.enable' => 'Включить настроенное приложение домена: --enable <домен>',
    'cli.commands.disable' => 'Отключить приложение домена: --disable <домен>',
    'cli.commands.toolchains' => 'Вывести список установленных наборов инструментов и использующих их доменов.',
    'cli.commands.install-toolchain' => 'Установить набор инструментов и дождаться результата: --install-toolchain <среда> <версия> [-no-wait]',
    'cli.commands.reconcile' => 'Согласовать службы приложений с Plesk (удалённые, переименованные или приостановленные домены).',
];
