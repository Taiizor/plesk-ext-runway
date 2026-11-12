<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/ms-MY.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ms-MY.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ms-MY.php';
$messages['app'] = require __DIR__ . '/app/ms-MY.php';
