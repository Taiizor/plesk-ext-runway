<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Bridge to the privileged helper (sbin/runway-helper), which runs as root.
 *
 * The payload is passed as JSON on stdin and never on the command line,
 * because command lines are visible to every local user through `ps`
 * and the payload may contain secrets (environment variables).
 */
class Modules_Runway_Helper
{
    const SCRIPT = 'runway-helper';

    /**
     * @param string $command
     * @param array $payload
     * @return array Decoded helper response without the "ok" flag
     * @throws Modules_Runway_Exception
     */
    public static function call($command, array $payload = [])
    {
        $stdin = json_encode((object)$payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($stdin === false) {
            throw new Modules_Runway_Exception('Could not encode the request for the helper.');
        }

        try {
            $result = pm_ApiCli::callSbin(self::SCRIPT, [$command], pm_ApiCli::RESULT_FULL, [], $stdin);
        } catch (Exception $e) {
            Modules_Runway_Log::err("runway-helper {$command} could not be executed: " . $e->getMessage());
            throw new Modules_Runway_Exception(
                pm_Locale::lmsg('errorHelperFailed', ['details' => $e->getMessage()])
            );
        }

        $stdout = is_array($result) && isset($result['stdout']) ? trim((string)$result['stdout']) : '';
        $stderr = is_array($result) && isset($result['stderr']) ? trim((string)$result['stderr']) : '';
        $data = json_decode($stdout, true);

        if (!is_array($data)) {
            Modules_Runway_Log::err("runway-helper {$command} returned malformed output. stdout: " . substr($stdout, 0, 2000)
                . ' stderr: ' . substr($stderr, 0, 2000));
            throw new Modules_Runway_Exception(
                pm_Locale::lmsg('errorHelperFailed', ['details' => substr($stderr !== '' ? $stderr : $stdout, 0, 500)])
            );
        }
        if (empty($data['ok'])) {
            $error = isset($data['error']) ? (string)$data['error'] : 'Unknown error';
            Modules_Runway_Log::debug("runway-helper {$command} failed: {$error}");
            $exception = new Modules_Runway_Exception($error);
            if (isset($data['code']) && is_string($data['code'])) {
                $exception->setHelperCode($data['code']);
            }
            throw $exception;
        }

        unset($data['ok']);
        return $data;
    }
}
