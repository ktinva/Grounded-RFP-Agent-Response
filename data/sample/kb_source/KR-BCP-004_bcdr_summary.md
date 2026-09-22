---
doc_id: KR-BCP-004
title: Business Continuity and Disaster Recovery Summary
version: "1.2"
effective_date: 2025-11-10
owner_team: security
approval_status: approved
---
## 1. Recovery Objectives

Kestrel Insight targets a Recovery Point Objective (RPO) of 4 hours and a Recovery Time Objective (RTO) of 12 hours in the event of a full regional outage.

## 2. Resilience Architecture

- Services run across three availability zones within the customer's hosting region.
- Production databases are replicated synchronously across availability zones, so the loss of a single availability zone does not cause data loss.
- Encrypted backup copies are stored in a separate AWS account to protect against account compromise.

## 3. Backup Retention

Encrypted database backups are retained for 90 days. Document storage uses object versioning, and deleted objects remain recoverable for 30 days.
===PAGE===
## 4. Testing

The disaster recovery plan is tested at least annually through a failover exercise. The most recent exercise, completed in October 2025, met the stated recovery objectives.

## 5. Business Continuity

Kestrel operates as a remote-first company with no single critical office location. Critical roles have designated backups, and the business continuity plan is reviewed annually by the executive team.

## 6. Customer Communication

During a service disruption, Kestrel posts status updates at status.kestrel-insight.example. Customers can subscribe to notifications by email or webhook.
