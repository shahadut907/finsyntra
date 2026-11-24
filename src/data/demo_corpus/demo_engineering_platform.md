# Northstar Analytics Engineering Platform Overview

This synthetic document applies only to the FinSyntra public demo tenant and describes Northstar Analytics' fictional engineering platform for demonstration purposes only.

The platform is organized into three core services: the Ledger API, the Reporting API, and the Notification Service, each owned by a dedicated engineering pod. The Ledger API team is the single point of contact for any schema change affecting financial records.

Northstar Analytics targets 99.9 percent monthly uptime (an error budget of about 43 minutes) for all customer-facing APIs, and 99.5 percent for internal batch services. All production changes require a peer-reviewed pull request, a passing automated test suite, and a documented rollback plan before merge.

Incidents are classified Sev1 through Sev4. A Sev1 incident (full customer-facing outage) requires the on-call engineer to open an incident channel within five minutes and page the engineering lead if unresolved after fifteen minutes. A postmortem is required for every Sev1 or Sev2 incident within three business days of resolution.

This document is classified for Engineering department access; general employees should consult the employee handbook for company-wide policies.
