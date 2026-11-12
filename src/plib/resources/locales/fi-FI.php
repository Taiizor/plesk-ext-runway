<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Finnish translation
// Locale loader: server strings (server/fi-FI.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/fi-FI.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/fi-FI.php';
$messages['app'] = require __DIR__ . '/app/fi-FI.php';
