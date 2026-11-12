<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Romanian translation
// Locale loader: server strings (server/ro-RO.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ro-RO.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ro-RO.php';
$messages['app'] = require __DIR__ . '/app/ro-RO.php';
