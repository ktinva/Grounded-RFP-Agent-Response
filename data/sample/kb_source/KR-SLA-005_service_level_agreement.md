---
doc_id: KR-SLA-005
title: Kestrel Insight Service Level Agreement
version: "3.1"
effective_date: 2026-01-01
owner_team: legal
approval_status: approved
---
## 1. Uptime Commitment

Kestrel will make Kestrel Insight available with a Monthly Uptime Percentage of at least 99.9% for the Business and Enterprise editions, and at least 99.95% for the Enterprise Premium edition. The Team edition is not covered by an uptime commitment.

Monthly Uptime Percentage is calculated as total minutes in the month minus minutes of Downtime, divided by total minutes in the month. Downtime means the service is unavailable to all users of a workspace, as measured by Kestrel's external monitoring.

## 2. Exclusions

Downtime does not include:

- Scheduled maintenance announced at least 5 business days in advance, limited to 8 hours per month and performed on Sundays between 02:00 and 06:00 UTC.
- Unavailability caused by the customer's systems, networks, or identity provider.
- Suspension of service under the terms of the customer agreement.
- Events beyond Kestrel's reasonable control.
===PAGE===
## 3. Service Credits

If Kestrel does not meet the uptime commitment in a calendar month, the customer is eligible for a service credit calculated as a percentage of the monthly fees for the affected workspace:

| Monthly Uptime Percentage | Service credit |
|---|---|
| Below commitment, at or above 99.0% | 10% |
| Below 99.0%, at or above 95.0% | 25% |
| Below 95.0% | 50% |

Credit requests must be submitted within 30 days of the end of the affected month. Service credits are the Customer's sole and exclusive remedy for any failure to meet the uptime commitment.
===PAGE===
## 4. Support Response Targets

| Severity | Definition | Initial response |
|---|---|---|
| Severity 1 | Critical production outage | Within 1 hour, 24x7 |
| Severity 2 | Major feature impaired | Within 4 business hours |
| Severity 3 | Minor issue or question | Within 1 business day |

## 5. Data Protection

Kestrel maintains a Recovery Point Objective (RPO) of 1 hour for customer data stored in Kestrel Insight.

## 6. Changes to this SLA

Kestrel may update this SLA with 30 days' written notice. Updates will not reduce the uptime commitment during a customer's current subscription term.
