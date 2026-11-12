<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Locale loader: server strings (server/fr-FR.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/fr-FR.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/fr-FR.php';
$messages['app'] = require __DIR__ . '/app/fr-FR.php';
