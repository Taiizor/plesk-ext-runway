<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Italian translation
//
// Locale loader: server strings (server/it-IT.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/it-IT.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/it-IT.php';
$messages['app'] = require __DIR__ . '/app/it-IT.php';
