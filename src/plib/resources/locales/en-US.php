<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/en-US.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/en-US.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/en-US.php';
$messages['app'] = require __DIR__ . '/app/en-US.php';
