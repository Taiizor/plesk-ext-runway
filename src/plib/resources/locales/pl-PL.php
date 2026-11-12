<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/pl-PL.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/pl-PL.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/pl-PL.php';
$messages['app'] = require __DIR__ . '/app/pl-PL.php';
