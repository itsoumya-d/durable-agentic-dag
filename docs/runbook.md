# Operations Runbook: durable-agentic-dag

## Deployment & Verification
1. Run CI test suite: `npm test && python3 -m unittest discover -s python_worker -p "test_*.py" -v`.
2. Verify static typechecking: `npm run lint`.
3. Check package integrity: `npm pack --dry-run`.

## Rollback Procedure
In the event of an operational regression or corrupted DAG state:
1. Revert to the previous stable release tag: `git checkout tags/v1.0.0`.
2. Clear in-memory checkpoint journals or purge stale state store indices.
3. Validate recovered state with `npm test`.
4. Deploy the rolled-back artifact to active worker nodes.
