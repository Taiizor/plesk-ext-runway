<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Czech translation
// Locale loader: server strings (server/cs-CZ.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/cs-CZ.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/cs-CZ.php';
$messages['app'] = require __DIR__ . '/app/cs-CZ.php';
