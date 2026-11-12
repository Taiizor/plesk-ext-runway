<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Greek translation
// Locale loader: server strings (server/el-GR.php, pm_Locale::lmsg) plus the 'app' section for the
// React frontend (app/el-GR.php, passed to the browser by the generated index.php).
$messages = require __DIR__ . '/server/el-GR.php';
$messages['app'] = require __DIR__ . '/app/el-GR.php';
