---
doc_id: KR-ARC-009
title: Technical Architecture and Integrations Guide
version: "1.5"
effective_date: 2026-05-01
owner_team: solutions_engineering
approval_status: approved
---
## 1. Architecture Overview

Kestrel Insight is built as containerized microservices running on Amazon Elastic Kubernetes Service (EKS). Document metadata is stored in PostgreSQL on Amazon RDS, source documents are stored in Amazon S3, and search uses a combination of keyword and vector indexes.

Generative features call a third-party large language model API over TLS 1.2 or higher. Only the passages needed to answer a request are sent to the model.

## 2. Data Flow

1. A document is uploaded through the web application, the API, or a connector.
2. The ingestion service extracts text (using OCR for scanned files) and splits it into passages.
3. Passages are indexed for keyword and semantic search, tagged with the collection's permissions.
4. At query time, only passages the user is permitted to see are retrieved and sent to the model.
===PAGE===
## 3. Integrations

Native connectors are available for SharePoint Online, Google Drive, Box, Confluence, and Amazon S3. Connectors synchronize incrementally and respect the source system's permissions at the time of sync.

## 4. APIs and Developer Tools

- REST API described by an OpenAPI 3.1 specification.
- Webhooks for document processed, extraction completed, and review completed events.
- An official Python SDK.

API rate limits are 600 requests per minute per workspace on Business, and 3,000 requests per minute per workspace on Enterprise and Enterprise Premium.
===PAGE===
## 5. Audit Log API and SIEM Export

Audit events are available through the Audit Log API for 180 days. Events can be streamed to Splunk or Datadog over HTTPS for longer retention in the customer's own SIEM.

## 6. Network Controls

- IP allowlisting is available on the Enterprise and Enterprise Premium editions.
- Private connectivity through AWS PrivateLink is available on the Enterprise Premium edition.
