<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Runs before the extension files are copied: only check requirements here. Keep it PHP 7.4
// compatible and free of global functions and constants (closures only).

// The root helper runs with this interpreter and needs this version or newer.
$python = '/usr/bin/python3';
$minimum = '3.8';
$supported = "Runway supports the distributions whose python3 is $minimum or newer"
    . ' (see https://github.com/Taiizor/plesk-ext-runway#requirements).';

/**
 * How to install a missing python3, by the distribution in /etc/os-release (ID, ID_LIKE and
 * VERSION_ID). Releases whose python3 package is older than $minimum get $supported instead,
 * as installing it would not help: Debian 10, Ubuntu 18.04, EL 7 and EL 8 (python3 is 3.6).
 */
$installHint = function () use ($supported) {
    $release = @file_get_contents('/etc/os-release');
    $field = function ($name) use ($release) {
        $found = is_string($release) && preg_match('/^' . $name . '=(.*)$/m', $release, $match);
        return $found ? strtolower(trim($match[1], " \t\r\"'")) : '';
    };
    $id = $field('ID');
    $version = $field('VERSION_ID');
    $family = array_merge([$id], preg_split('/\s+/', $field('ID_LIKE'), -1, PREG_SPLIT_NO_EMPTY));
    // First release with a recent enough python3, by ID. Derivatives of Debian and Ubuntu number
    // their releases differently (not compared); RHEL clones and derivatives like RHEL.
    if (array_intersect(['debian', 'ubuntu'], $family)) {
        $manager = 'apt-get';
        $first = ['debian' => '11', 'ubuntu' => '20.04'];
    } elseif (array_intersect(['rhel', 'centos', 'fedora', 'almalinux', 'rocky', 'cloudlinux'], $family)) {
        $manager = 'dnf';
        $first = [$id => $id === 'fedora' ? '32' : '9'];
    } else {
        return 'Install it with the package manager of the distribution.';
    }
    if ($version !== '' && isset($first[$id]) && version_compare($version, $first[$id], '<')) {
        return $supported;
    }
    return 'Install it with: ' . $manager . ' install -y python3';
};

/** Printable excerpt of a command's output for a problem message. */
$excerpt = function ($text) {
    $text = trim((string)preg_replace('/[^\x20-\x7e]+/', ' ', (string)$text));
    return strlen($text) > 160 ? substr($text, 0, 157) . '...' : $text;
};

/**
 * Version of the python3 interpreter ("3.12.3"), or null with the reason in $reason when it could
 * not be started, failed, did not answer in time or printed anything else than a version. Runs
 * without a shell; -E and -S ignore the PYTHON* variables and the site packages (supported by
 * every python3, unlike -I).
 */
$pythonVersion = function ($python, &$reason) use ($excerpt) {
    $timeout = 10;
    $code = 'import sys; sys.stdout.write("%d.%d.%d" % tuple(sys.version_info[:3]))';
    $pipes = [];
    $process = @proc_open(
        [$python, '-E', '-S', '-c', $code],
        [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
        $pipes
    );
    if (!is_resource($process)) {
        $reason = 'it could not be started';
        return null;
    }
    // Reads stdout and stderr together until both end, then waits for the exit, all before a
    // deadline: a python3 that hangs, or fills one pipe while the other is read, must not block
    // the installation.
    $deadline = microtime(true) + $timeout;
    $open = [1 => $pipes[1], 2 => $pipes[2]];
    $data = [1 => '', 2 => ''];
    foreach ($open as $pipe) {
        stream_set_blocking($pipe, false);
    }
    $exit = null;
    while ($exit === null && ($left = $deadline - microtime(true)) > 0) {
        if (!$open) {
            $status = proc_get_status($process);
            if ($status['running']) {
                usleep(10000);
            } else {
                $exit = $status;
            }
            continue;
        }
        $read = array_values($open);
        $write = null;
        $except = null;
        $ready = @stream_select($read, $write, $except, (int)$left, (int)(fmod($left, 1) * 1000000));
        if ($ready === false) {
            usleep(10000); // e.g. interrupted by a signal: try again until the deadline
        }
        if (!$ready) {
            continue;
        }
        foreach ($open as $index => $pipe) {
            if (!in_array($pipe, $read, true)) {
                continue;
            }
            $chunk = fread($pipe, 8192);
            if ($chunk === false || ($chunk === '' && feof($pipe))) {
                fclose($pipe);
                unset($open[$index]);
            } elseif (strlen($data[$index]) < 65536) {
                $data[$index] .= $chunk;
            }
        }
    }
    if ($exit === null) {
        proc_terminate($process, 9);
        foreach ($open as $pipe) {
            fclose($pipe);
        }
        proc_close($process);
        $reason = "it did not answer within $timeout s";
        return null;
    }
    proc_close($process);
    $output = $data[1];
    $errors = $data[2];
    $detail = $excerpt($errors !== '' ? $errors : $output);
    if ($exit['signaled']) {
        $reason = 'it was terminated by signal ' . $exit['termsig'] . ($detail !== '' ? ': ' . $detail : '');
        return null;
    }
    // The exit code is -1 when it is unknown (the caller ignores SIGCHLD): the output decides.
    if ($exit['exitcode'] > 0) {
        $reason = 'it failed with exit code ' . $exit['exitcode'] . ($detail !== '' ? ': ' . $detail : '');
        return null;
    }
    $output = trim($output);
    if (!preg_match('/^\d+\.\d+(?:\.\d+)?$/', $output)) {
        $detail = $excerpt($output);
        $reason = $detail !== '' ? 'it printed "' . $detail . '" instead of its version' : 'it printed no version';
        return null;
    }
    return $output;
};

$problems = [];
if (stripos(PHP_OS, 'Linux') !== 0) {
    $problems[] = 'This extension supports Linux servers only.';
}
if (!is_dir('/run/systemd/system')) {
    $problems[] = 'systemd is required (it must be the init system of the server).';
}
// Without these functions (disable_functions of the PHP configuration) the version cannot be
// checked here.
$disabled = array_map('trim', explode(',', (string)ini_get('disable_functions')));
$canRun = true;
foreach (['proc_open', 'proc_get_status', 'proc_terminate', 'proc_close', 'stream_select'] as $function) {
    $canRun = $canRun && function_exists($function) && !in_array($function, $disabled, true);
}
if (!is_executable($python)) {
    $problems[] = "python3 $minimum or newer is required ($python). " . $installHint();
} elseif ($canRun) {
    $reason = '';
    $version = $pythonVersion($python, $reason);
    if ($version === null) {
        $problems[] = "python3 $minimum or newer is required, but the version of $python could not be"
            . " determined ($reason).";
    } elseif (version_compare($version, $minimum, '<')) {
        $problems[] = "python3 $minimum or newer is required, but $python is version $version. $supported";
    }
}
if (!is_executable('/bin/bash')) {
    $problems[] = '/bin/bash is required.';
}

if ($problems) {
    echo "Runway cannot be installed:\n - " . implode("\n - ", $problems) . "\n";
    exit(1);
}
exit(0);
