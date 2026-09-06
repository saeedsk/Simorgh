"""Storage engines behind `LedgerClient`: `memory` (tests), `jsonl`
(default; v1-compatible files), `sqlite` (multi-process on one host),
`dynamodb` (optional; lazy boto3). Each implements `api.LedgerBackend`.
"""
