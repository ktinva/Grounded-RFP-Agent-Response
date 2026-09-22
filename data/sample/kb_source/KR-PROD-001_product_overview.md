---
doc_id: KR-PROD-001
title: Kestrel Insight Product Overview
version: "4.0"
effective_date: 2026-02-01
owner_team: product
approval_status: approved
---
## 1. What Kestrel Insight Is

Kestrel Insight is an AI-assisted document intelligence platform that helps enterprise teams find, extract, and summarize information across contracts, reports, policies, and technical documentation. It is built by Kestrel Ridge Software, Inc. and is delivered as a cloud service.

Typical users are legal operations, procurement, finance, and customer-facing technical teams who work with large volumes of long, unstructured documents.

## 2. Core Capabilities

- **Semantic search** across document collections, with every result linked to its source document and page.
- **Summarization and field extraction** for contracts, invoices, statements of work, and technical reports, using configurable extraction templates.
- **Grounded question answering** over approved document collections. Answers include citations to the source document and page number.
- **Workflow automation** that sends extracted fields to downstream systems through webhooks and the REST API.
- **Collections and permissions** so that each team only searches the documents it is entitled to see.

## 3. Supported File Types

Kestrel Insight ingests PDF, DOCX, XLSX, PPTX, TXT, and HTML files, as well as scanned images (PNG, JPEG, TIFF), which are processed with built-in optical character recognition (OCR). The maximum file size is 500 MB per file.

## 4. Supported Languages

The user interface is available in English, French, German, Spanish, and Japanese. Document processing (search, extraction, and summarization) supports 24 languages; the current list is maintained in the in-product help center.
===PAGE===
## 5. Editions

| Capability | Team | Business | Enterprise | Enterprise Premium |
|---|---|---|---|---|
| Single sign-on (SAML / OIDC) | No | Yes | Yes | Yes |
| SCIM user provisioning | No | No | Yes | Yes |
| Custom roles | No | No | Yes | Yes |
| Customer-managed encryption keys | No | No | Yes | Yes |
| Dedicated single-tenant deployment | No | No | No | Yes |
| Uptime commitment | None | 99.9% | 99.9% | 99.95% |

## 6. Deployment Model

Kestrel Insight is delivered as software-as-a-service (SaaS) hosted on Amazon Web Services (AWS). All editions run on a multi-tenant architecture, except Enterprise Premium, which can optionally be deployed as a dedicated single-tenant environment.

Kestrel Insight is not available for on-premises or customer-hosted deployment.

## 7. Hosting Regions and Data Residency

Customers select a hosting region when their workspace is provisioned. Customer data is stored and processed in the selected region. Available hosting regions are the United States, the European Union, and the United Kingdom.

The hosting region cannot be changed after provisioning without a supported migration, which is arranged through Kestrel Customer Success.
===PAGE===
## 8. Identity and Access

- Single sign-on through SAML 2.0 and OpenID Connect (OIDC). Kestrel tests and supports Okta, Microsoft Entra ID, and Google Workspace as identity providers.
- SCIM 2.0 user and group provisioning on the Enterprise and Enterprise Premium editions.
- Role-based access control with four built-in roles: Owner, Admin, Editor, and Viewer. Custom roles are available on the Enterprise and Enterprise Premium editions.
- Multi-factor authentication (MFA) is enforced for all local accounts that do not sign in through SSO.

## 9. Availability

Kestrel Insight is backed by a 99.9% monthly uptime commitment on the Business and Enterprise editions. Full terms, exclusions, and service credits are defined in the Kestrel Insight Service Level Agreement.

## 10. Where to Find More Detail

- Security controls: Kestrel Insight Security Whitepaper
- Certifications and audits: Compliance and Certifications Overview
- Data protection terms: Data Processing Addendum
- AI data handling: AI Data Use and Model Governance
- Integrations and APIs: Technical Architecture and Integrations Guide
