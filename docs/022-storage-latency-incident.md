# Storage latency incident: Beelink, 20 October 2026

## Outcome

Moving OakGate's active SQLite storage from the external USB drive to the internal
SSD removed a major performance bottleneck. Direct health response time fell from
2.693457 seconds to 0.002265 seconds (about 1,200 times faster in these individual
measurements). Inbox phases subsequently completed in about 0.10–0.30 seconds.
The operator reported almost immediate payment detection and successful Lightning
receiving from multiple external wallets. These observations are not a latency SLA
or a benchmark proving every payment was settled within that time.

## Symptoms and evidence

Symptoms included delayed Clear receiving, repeated wallet-busy responses,
background timeouts, and intermittent Docker health-check failures. Earlier
startup logs showed discovery phases taking 41–56 seconds. Later diagnostics
isolated long database operations:

| Observation | Measured value |
| --- | --- |
| Inbox custody lease renewal | 9.094 seconds |
| Inbox scheduling query/write | 4.036–6.006 seconds |
| Custody lease release | 12.913 seconds |
| USB drive write latency in live iostat samples | 268–1,282 milliseconds |
| USB drive flush latency in live samples | 774–1,413 milliseconds |
| Host CPU I/O wait in live samples | 61–92% |

Both payment and inbox workers logged `OperationalError`. At the time the logs
recorded only the exception type, so “database is locked” was suspected, not
confirmed. Elapsed database timings included thread scheduling as well as SQL
and commit time. The disk measurements supplied independent evidence of severe
storage latency.

The old location was `/mnt/bitcoin/oakgate` on `/dev/sdb1`, a local ext4 filesystem
mounted read/write. It had 810 GB free and only 1% inode use: capacity exhaustion
was not the problem. The device reported USB transport and rotational media.
No matching kernel error lines were supplied during the investigation; that does
not establish the drive's health or rule out intermittent connection problems.

The destination `/var/lib` is on the internal SATA SSD through the root LVM/ext4
filesystem. It had about 190 GB free before the move.

## Interpretation

Small durable database writes were waiting on a high-latency storage path. Slow
commits can prolong SQLite write locks and delay other operations, including the
lease updates that serialize wallet mutations. Low CPU usage did not imply the
server was healthy: much of its time was spent waiting for I/O.

The evidence implicates the old storage path; it does not isolate USB bandwidth,
the drive mechanism, enclosure/controller behavior, or competing workloads as
the sole cause. The move changed both the medium and connection. Do not conclude
that all USB storage is unsuitable or that SQLite itself needs replacing.

## Deployment change

Current Beelink configuration:

```dotenv
OAKGATE_DATA_DIR=/var/lib/oakgate
```

The container still mounts this directory at `/app/data`. Its database remains
`/app/data/custody.sqlite3`; on this host the active file is now
`/var/lib/oakgate/custody.sqlite3`. Repository defaults may still name the old
external path: the operator's `.env` selects the actual host directory.

Only OakGate was stopped for migration. The complete stopped data directory was
copied with ownership and permissions preserved, checked with an rsync checksum
dry run, and the app recreated with the new mount. `OAKGATE_CUSTODY_KEY` was not
changed. Keycloak and Redis stayed running.

For future moves:

1. Verify destination storage, free space and an empty destination directory.
2. Stop the app and confirm it has fully stopped before copying.
3. Copy the complete data directory, including any journal/WAL files, preserving
   ownership and permissions. Verify the copy before starting the new instance.
4. Change only the host data path and recreate the app with `--no-deps`.
5. Verify health, login, balances and native Acorn transaction history. Confirm
   an uncertain payment's outcome before attempting another payment.
6. Update backup jobs to the new active location.

Once new writes occur, the original USB copy is stale. Never switch back to it as
an ordinary rollback: it may omit payment outcomes and recovery checkpoints. Do
not run old and new copies concurrently. Use the supported recovery procedure
instead of deleting journals, clearing leases manually, or resending uncertain
payments. See [storage and backups](008-identity-storage-backups.md).

## Software safeguards retained

Earlier changes fixed Acorn's cancellation-related local lock leak, separated
inbox discovery and settlement, removed short cancellation deadlines around
receipt writes, renewed custody leases, and drained active work during graceful
shutdown. Inbox SQLite operations were moved off the HTTP event loop. Uvicorn
explicitly uses asyncio to avoid the observed uvloop SSL closed-transport path.
These safeguards remain useful but did not, by themselves, eliminate slow disk
commits. The SSL workaround is separate from the storage finding.

No durability setting was disabled to obtain the improvement. Acorn remains
responsible for private-key operations, proof delivery and transaction history;
OakGate retains its encrypted payment journals and duplicate-payment guards.
Early “Payment detected” is an incoming-transfer indication, not confirmed credit.

## If it happens again

Run these read-only checks during the slowdown, using the actual configured path:

```bash
findmnt -T /var/lib/oakgate
df -h /var/lib/oakgate
df -i /var/lib/oakgate
lsblk -d -o NAME,MODEL,TRAN,ROTA,SIZE
iostat -xz 1 10
docker stats --no-stream
docker compose logs --since=10m --tail=150 app
curl --max-time 10 -sS -w '\nDirect: %{time_total}s\n' http://127.0.0.1:8801/health
```

Use the live iostat intervals, not just the first since-boot report. Inspect
`r_await`, `w_await`, `f_await`, queue depth and CPU I/O wait. If available,
`sudo iotop -oPa` helps identify competing processes. Check recent kernel logs for
I/O errors, USB resets and filesystem warnings. Redact secrets before sharing
logs. Capture SQLite error codes if OperationalError recurs; don't assume every
such error means lock contention.

Keep active transactional databases on suitable low-latency storage and maintain
consistent backups elsewhere. LND and Spurline were not migrated as part of this
incident; neither service's current performance nor future migration safety should
be inferred from OakGate's result.
