# Multi-Client Load Test — Runbook

Exact commands used to run the 40-simulated-client aggregate load test
(2026-11-12). Results and analysis are in `docs/load_test_results.md`
("Multi-client aggregate validation (2026-11-12)"); this file is just the
reproducible command sequence. All commands are PowerShell, run from the
repo root, in the same terminal throughout (env vars don't carry across
terminals).

Requires `loadtest/locustfile.py`'s `LOAD_TEST_API_KEYS` support (added
2026-11-12 — round-robins a distinct key across simulated users instead of
every user sharing one client's rate-limit bucket).

`scripts/manage_api_keys.py create`/`revoke` must be run by you, not the
assistant — blocked by the harness's permission classifier as
credential-granting.

## 1. Create the test keys

```powershell
$py = "C:\Apps\Anaconda\fin_api\python.exe"
$keys = @()
1..40 | ForEach-Object {
    $name = "loadtest-multi-{0:D2}" -f $_
    $out = & $py scripts\manage_api_keys.py create --client-name $name --scopes standard:read,confidential:read
    $keys += ($out | Select-String '^bwfin_').Line.Trim()
    Write-Host "created $name"
}
Write-Host "Created $($keys.Count) keys"
```

Raw keys only ever live in the `$keys` array in memory for this terminal
session — never written to a file.

## 2. Assign the keys to env vars

```powershell
$env:LOAD_TEST_API_KEYS = $keys -join ","
$env:LOAD_TEST_VARY_PARAMS = "1"   # randomised params -> mostly cache-miss, the more realistic setting
```

## 3. Start the authenticated proxy (separate terminal, left running)

```powershell
gcloud run services proxy fin-analytics-api --region europe-west4 --project fin-analytics-api --port 8080
```

## 4. Short sanity check (~20s)

Confirms the key-rotation code works and there's no immediate problem
before committing to the full 2-minute run.

```powershell
python -m locust -f loadtest/locustfile.py --host http://localhost:8080 --headless -u 40 -r 10 -t 20s
```

## 5. Full test (2 min, 120 users / 40 keys = 3 users per key on average)

```powershell
python -m locust -f loadtest/locustfile.py --host http://localhost:8080 --headless -u 120 -r 15 -t 2m --csv loadtest/results_multiclient
```

Produces `loadtest/results_multiclient_{stats,failures,exceptions,stats_history}.csv`
(gitignored via `loadtest/results*`).

## 6. Revoke all test keys + clean up

```powershell
1..40 | ForEach-Object {
    & $py scripts\manage_api_keys.py revoke --client-name ("loadtest-multi-{0:D2}" -f $_)
}
Remove-Item Env:\LOAD_TEST_API_KEYS -ErrorAction SilentlyContinue
Remove-Item Env:\LOAD_TEST_VARY_PARAMS -ErrorAction SilentlyContinue
```

Revocation takes effect within up to 5 minutes on warm instances
(`CACHE_TTL_SECONDS`). Also stop the `gcloud run services proxy` process
from step 3 if it's still running.
