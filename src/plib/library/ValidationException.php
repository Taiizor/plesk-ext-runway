<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Input validation failed. Carries the errors keyed by field, which the API returns as
 * {"status": "error", "errors": {"field": ["message", ...]}}.
 */
class Modules_Runway_ValidationException extends Modules_Runway_Exception
{
    /** @var array field => string[] */
    private $errors;

    /**
     * @param array $errors field => string[]
     */
    public function __construct(array $errors)
    {
        $this->errors = $errors;
        $first = reset($errors);
        parent::__construct(is_array($first) ? (string)reset($first) : (string)$first);
    }

    /**
     * @return array field => string[]
     */
    public function getErrors()
    {
        return $this->errors;
    }
}
