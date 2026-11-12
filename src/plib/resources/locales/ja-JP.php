<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/ja-JP.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ja-JP.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ja-JP.php';
$messages['app'] = require __DIR__ . '/app/ja-JP.php';
