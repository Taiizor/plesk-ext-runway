<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Chinese (Simplified) translation
// Locale loader: server strings (server/zh-CN.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/zh-CN.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/zh-CN.php';
$messages['app'] = require __DIR__ . '/app/zh-CN.php';
