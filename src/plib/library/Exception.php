<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Expected failure whose message is safe to show to the user.
 */
class Modules_Runway_Exception extends pm_Exception
{
    /**
     * @var string|null Machine-readable reason reported by the helper ("code" of its error
     *                  answer, e.g. not_empty), null for other failures
     */
    private $helperCode = null;

    /**
     * @param string|null $code
     * @return $this
     */
    public function setHelperCode($code)
    {
        $this->helperCode = $code !== null ? (string)$code : null;
        return $this;
    }

    /**
     * @return string|null
     */
    public function getHelperCode()
    {
        return $this->helperCode;
    }
}
