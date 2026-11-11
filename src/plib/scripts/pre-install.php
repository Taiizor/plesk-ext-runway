<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Runs before the extension files are copied: only check requirements here.

$problems = [];
if (stripos(PHP_OS, 'Linux') !== 0) {
    $problems[] = 'This extension supports Linux servers only.';
}
if (!is_dir('/run/systemd/system')) {
    $problems[] = 'systemd is required (it must be the init system of the server).';
}
if (!is_executable('/usr/bin/python3')) {
    $problems[] = 'python3 is required (/usr/bin/python3). Install it with: apt-get install -y python3';
}
if (!is_executable('/bin/bash')) {
    $problems[] = '/bin/bash is required.';
}

if ($problems) {
    echo "Runway cannot be installed:\n - " . implode("\n - ", $problems) . "\n";
    exit(1);
}
exit(0);
