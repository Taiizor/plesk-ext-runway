<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/tr-TR.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/tr-TR.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/tr-TR.php';
$messages['app'] = require __DIR__ . '/app/tr-TR.php';
