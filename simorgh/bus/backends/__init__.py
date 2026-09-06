"""The three `BusBackend` implementations (docs/blueprint/subsystems/01-bus.md
sections 5.3-5.5): `memory` (asyncio, in-process), `sqlite` (one WAL file
shared by processes on a host), `aws` (SNS + SQS, optional, lazy boto3)."""
