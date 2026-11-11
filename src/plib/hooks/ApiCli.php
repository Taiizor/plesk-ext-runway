<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Command line interface: "plesk ext runway --<command> [arguments]" (docs/DESIGN.md
 * section 9). Plesk maps "--install-toolchain" to installToolchainCommand(), lists the
 * commands with "--help" (descriptions: locale keys "cli.commands.<command>") and runs them
 * in the administrator's context. The logic lives in Modules_Runway_Cli.
 */
class Modules_Runway_ApiCli extends pm_Hook_ApiCli
{
    public function listCommand()
    {
        $this->dispatch('list');
    }

    public function statusCommand()
    {
        $this->dispatch('status');
    }

    public function startCommand()
    {
        $this->dispatch('start');
    }

    public function stopCommand()
    {
        $this->dispatch('stop');
    }

    public function restartCommand()
    {
        $this->dispatch('restart');
    }

    public function deployCommand()
    {
        $this->dispatch('deploy');
    }

    public function enableCommand()
    {
        $this->dispatch('enable');
    }

    public function disableCommand()
    {
        $this->dispatch('disable');
    }

    public function toolchainsCommand()
    {
        $this->dispatch('toolchains');
    }

    public function installToolchainCommand()
    {
        $this->dispatch('install-toolchain');
    }

    public function reconcileCommand()
    {
        $this->dispatch('reconcile');
    }

    /**
     * @param string $command
     */
    private function dispatch($command)
    {
        // getArguments() returns everything after "plesk ext runway", the command included.
        $arguments = array_values(array_map('strval', (array)$this->getArguments()));
        $index = array_search('--' . $command, $arguments, true);
        if ($index !== false) {
            array_splice($arguments, $index, 1);
        }
        $cli = new Modules_Runway_Cli(
            function ($text) {
                $this->stdout($text);
            },
            function ($text) {
                $this->stderr($text);
            }
        );
        $code = $cli->execute($command, $arguments);
        if ($code !== Modules_Runway_Cli::EXIT_OK) {
            $this->exitCode($code);
        }
    }
}
