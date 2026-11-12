<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Portuguese (Brazil) translation
// Locale loader: server strings (server/pt-BR.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/pt-BR.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/pt-BR.php';
$messages['app'] = require __DIR__ . '/app/pt-BR.php';
