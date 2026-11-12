<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/hu-HU.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/hu-HU.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/hu-HU.php';
$messages['app'] = require __DIR__ . '/app/hu-HU.php';
