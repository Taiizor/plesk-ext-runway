<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Norwegian Bokmål translation
// Locale loader: server strings (server/nb-NO.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/nb-NO.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/nb-NO.php';
$messages['app'] = require __DIR__ . '/app/nb-NO.php';
