<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/zh-TW.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/zh-TW.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/zh-TW.php';
$messages['app'] = require __DIR__ . '/app/zh-TW.php';
