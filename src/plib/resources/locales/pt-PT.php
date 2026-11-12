<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Portuguese (Portugal) translation
// Locale loader: server strings (server/pt-PT.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/pt-PT.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/pt-PT.php';
$messages['app'] = require __DIR__ . '/app/pt-PT.php';
