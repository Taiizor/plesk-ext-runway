<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Korean translation
// Locale loader: server strings (server/ko-KR.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ko-KR.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ko-KR.php';
$messages['app'] = require __DIR__ . '/app/ko-KR.php';
