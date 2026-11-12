<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Catalan translation
// Locale loader: server strings (server/ca-ES.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ca-ES.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ca-ES.php';
$messages['app'] = require __DIR__ . '/app/ca-ES.php';
