<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// German translation
// Locale loader: server strings (server/de-DE.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/de-DE.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/de-DE.php';
$messages['app'] = require __DIR__ . '/app/de-DE.php';
