# Incident response

This process follows the preparation, detection, response, and recovery approach in NIST SP 800-61 Rev. 3.

1. Declare an incident owner and severity. Critical means confirmed cross-tenant exposure, credential compromise, destructive bypass, or prolonged complete outage.
2. Preserve audit logs and timestamps; never copy raw customer content into chat or public tickets.
3. Contain with API-key revocation, gateway emergency revocation, disabled bootstrap, traffic isolation, or rollback to the last verified release.
4. Notify affected customers through the documented security contact and status channel. State known scope, mitigations, and the next update time; do not speculate.
5. Recover from a verified backup, run `verify ga readiness`, tenant-isolation tests, and security regression tests before reopening traffic.
6. Publish an appropriate post-incident review covering impact, timeline, contributing controls, corrective actions, and owners.

Targets: acknowledge critical alerts within 15 minutes, begin customer communication within one hour of confirmed customer impact, and provide updates at least hourly while critical impact continues. These are readiness targets, not a claimed staffed SLA.
