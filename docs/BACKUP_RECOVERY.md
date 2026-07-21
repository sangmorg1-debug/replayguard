# Backup and recovery

Use an encrypted storage volume and a destination outside the live database directory. A backup contains customer metadata and may contain encrypted customer content.

```powershell
verify ga backup --database .verify/hosted.sqlite3 --output D:\replayguard-backups\daily.sqlite3
verify ga restore-copy --backup D:\replayguard-backups\daily.sqlite3 --output .verify/recovery-test.sqlite3
verify ga readiness --database .verify/recovery-test.sqlite3
```

The backup command uses SQLite's online backup API and emits a SHA-256 manifest. Restore always writes a distinct copy, performs an integrity check, and never overwrites the live database. Promoting a restored copy requires an operator-controlled maintenance window, verified master-key availability, application shutdown, an additional live backup, and an atomic deployment procedure appropriate to the host.

Initial objectives: RPO 24 hours and RTO four hours. Do not advertise these as achieved until scheduled off-host backups and timed quarterly restoration drills demonstrate them.
