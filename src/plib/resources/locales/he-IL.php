<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Hebrew translation
// Locale loader: server strings (server/he-IL.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/he-IL.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/he-IL.php';
$messages['app'] = require __DIR__ . '/app/he-IL.php';
