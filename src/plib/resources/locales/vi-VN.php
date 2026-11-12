<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Vietnamese translation
// Locale loader: server strings (server/vi-VN.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/vi-VN.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/vi-VN.php';
$messages['app'] = require __DIR__ . '/app/vi-VN.php';
