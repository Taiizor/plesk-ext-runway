<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Spanish (Spain) translation
// Locale loader: server strings (server/es-ES.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/es-ES.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/es-ES.php';
$messages['app'] = require __DIR__ . '/app/es-ES.php';
