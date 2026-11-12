<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/ar.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/ar.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/ar.php';
$messages['app'] = require __DIR__ . '/app/ar.php';
