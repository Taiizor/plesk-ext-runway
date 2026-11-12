<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/nl-NL.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/nl-NL.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/nl-NL.php';
$messages['app'] = require __DIR__ . '/app/nl-NL.php';
