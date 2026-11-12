<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Ukrainian translation
// Locale loader: server strings (server/uk-UA.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/uk-UA.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/uk-UA.php';
$messages['app'] = require __DIR__ . '/app/uk-UA.php';
