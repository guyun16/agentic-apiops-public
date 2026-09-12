-- Add the independently implemented local benchmark endpoint's 401 contract.
-- Preserve all existing operations and response schemas; safe to rerun.
INSERT INTO api_response_schema
    (api_id, project_id, status_code, description, media_type, schema_json, created_at)
SELECT api_id, project_id, '401', 'Missing or invalid benchmark API key', 'application/json',
    '{"type":"object","required":["success","code"],"properties":{"success":{"type":"boolean","enum":[false]},"code":{"type":"string","enum":["AUTH_UNAUTHORIZED"]}}}',
    CURRENT_TIMESTAMP(3)
FROM api_endpoint e
WHERE e.project_id = 41 AND e.api_id = 'stage21-auth-api-key'
    AND e.path = '/stage21/auth-check' AND e.http_method = 'POST'
    AND NOT EXISTS (SELECT 1 FROM api_response_schema r
        WHERE r.project_id = e.project_id AND r.api_id = e.api_id AND r.status_code = '401');
