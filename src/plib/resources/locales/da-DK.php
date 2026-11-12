<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Danish translation
//
// Locale loader: server strings (server/da-DK.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/da-DK.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/da-DK.php';
$messages['app'] = require __DIR__ . '/app/da-DK.php';
