<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Thai translation
// Locale loader: server strings (server/th-TH.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/th-TH.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/th-TH.php';
$messages['app'] = require __DIR__ . '/app/th-TH.php';
