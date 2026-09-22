"""Company policy the agents enforce: topics, owners, and hard escalation rules.

Kept as plain data so legal, security, and SE leads can review and edit it
without reading agent code. Rules run BEFORE any model call, so a sensitive
question never gets a free-form draft, regardless of what the model thinks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TEAMS = ("legal", "security", "product", "solutions_engineering")

# Topic taxonomy used by the classifier. Each topic has an owning team, which is
# where unanswerable or conflicting questions on that topic are routed.
TOPICS: dict[str, tuple[str, str]] = {
    "security_controls": ("security", "encryption, access control, vulnerability management, logging, "
                          "monitoring, security training, personnel security, cryptography"),
    "compliance_certifications": ("security", "SOC 2, ISO 27001, FedRAMP, PCI DSS, other audits and frameworks"),
    "resilience": ("security", "backups, disaster recovery, RPO/RTO, business continuity"),
    "incident_history": ("security", "whether breaches or incidents have occurred"),
    "privacy_contract": ("legal", "DPA terms, customer breach-notification timelines, data residency and "
                         "hosting regions, subprocessors, deletion at termination, agreements to sign "
                         "(BAA, DPA), audit rights"),
    "legal_commercial": ("legal", "liability, indemnity, warranties, SLA remedies and penalties, contract terms, "
                         "escrow, insurance, litigation, financial statements"),
    "pricing": ("solutions_engineering", "prices, discounts, quotes, licensing costs"),
    "product_capabilities": ("product", "features, editions, file types, languages, accessibility, "
                             "mobile apps, AI features and models, roadmap"),
    "architecture_integrations": ("solutions_engineering", "architecture, APIs, connectors, integrations, "
                                  "environments and sandboxes, network connectivity, deployment options"),
    "support_operations": ("solutions_engineering", "support plans, response times, maintenance, releases, "
                           "customer references, onboarding"),
    "availability_sla": ("legal", "uptime commitments, service credits, SLA exclusions"),
    "general": ("solutions_engineering", "anything else"),
}


def topic_owner(topic: str | None) -> str:
    return TOPICS.get(topic or "general", TOPICS["general"])[0]


@dataclass(frozen=True)
class EscalationRule:
    name: str
    team: str
    pattern: re.Pattern
    reason: str


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.I)


# Hard escalation list (design decision D7). Order matters: first match wins.
ESCALATION_RULES: tuple[EscalationRule, ...] = (
    EscalationRule("liability", "legal", _r(r"\bliabilit(y|ies)\b.*\b(cap|limit|maximum|amount)|\b(cap|limit)\w* on (your )?liabilit|\bliable\b"),
                   "Liability terms are negotiated by Legal."),
    EscalationRule("indemnity", "legal", _r(r"\bindemni"), "Indemnification is a contractual commitment."),
    EscalationRule("breach_history", "security",
                   _r(r"\b(experienced|suffered|had|disclose|describe)\b.*\b(breach(es)?|incidents?)\b.*\b(past|last|since|previous|prior)\b"
                      r"|\b(breach(es)?|incidents?)\b.*\b(in the )?(past|last) \w+ (years?|months?)"),
                   "Breach history is disclosed only by Security after review."),
    EscalationRule("pentest_report", "security",
                   _r(r"\b(full|complete|entire)\b.*\b(pen(etration)?[ -]?test)|\bpen(etration)?[ -]?test\b.*\b(report|findings)\b"),
                   "Penetration test reports are shared only by Security under NDA."),
    EscalationRule("pricing", "solutions_engineering",
                   _r(r"\b(discount|pricing|price|quote|cost of|fees? for|rate card)\b"),
                   "Pricing is handled by the deal team through Solutions Engineering."),
    EscalationRule("roadmap_commitment", "product",
                   _r(r"\b(commit|promise)(s|ted|ting)?\s+to\b.*\b(deliver|release|launch|ship|offer|support)\w*\b"
                      r"|\b(confirm|guarantee)\b.*\bwill be (released|delivered|available|launched)\b"
                      r"|\b(released?|delivered|launched|available)\b.*\b(by (q[1-4] |mid-?|end of )?20\d\d|within the next \d+ months)\b"
                      r"|\broadmap\b.*\bcommit"),
                   "Roadmap commitments require Product approval."),
    EscalationRule("customer_paper", "legal",
                   _r(r"\b(sign|accept|use|execute)\b.*\b(our|customer'?s?|organization'?s?)\b.*\b(dpa|data processing|agreement|terms|template|paper)\b"),
                   "Accepting customer contract terms requires Legal."),
    EscalationRule("onsite_audit", "legal", _r(r"\bon-?site\b.*\b(audit|inspection)s?|\bright to audit\b"),
                   "Audit rights are governed by the DPA and negotiated by Legal."),
    EscalationRule("financials", "legal",
                   _r(r"\b(financial statements?|balance sheet|income statement|audited accounts|financial stability)\b"),
                   "Financial disclosures are approved by Legal/Finance."),
    EscalationRule("litigation", "legal",
                   _r(r"\b(litigation|lawsuits?|legal proceedings|regulatory (action|investigation)s?|government investigations?)\b"),
                   "Litigation disclosures are made by Legal."),
    EscalationRule("uptime_guarantee", "legal",
                   _r(r"\b100 ?% (uptime|availability)|\bzero downtime\b|\bliquidated damages\b|\bpenalt(y|ies)\b"),
                   "Commitments beyond the published SLA require Legal."),
    EscalationRule("references", "solutions_engineering",
                   _r(r"\b(customer )?references?\b.*\b(contact|names?|phone|clients?|customers?)\b|\bclients? we may contact\b"
                      r"|\b(contact|names?|phone)\b.*\b(customers?|clients?)\b.*\breferences?\b"),
                   "Customer references need the customer's consent; SE coordinates."),
    EscalationRule("escrow", "legal", _r(r"\bescrow\b"), "Source code escrow is a contractual commitment."),
    EscalationRule("ai_warranty", "product",
                   _r(r"\b(warrant|guarantee)\w*\b.*\b(accura|correct|never produce|always be accurate)"),
                   "Warranties about AI output accuracy require Product and Legal approval."),
    EscalationRule("insurance", "legal", _r(r"\binsurance\b"), "Insurance details are provided by Legal/Finance."),
)

# A question that points at a document we were not given cannot be answered.
MISSING_ATTACHMENT = _r(r"\b(appendix|exhibit|annex|attachment|attached)\b")
_SCHEDULE_REF = re.compile(r"\bSchedule [A-Z0-9]{1,3}\b|\bSecurity Schedule\b")  # case-sensitive on purpose


def match_escalation(question: str) -> EscalationRule | None:
    for rule in ESCALATION_RULES:
        if rule.pattern.search(question):
            return rule
    return None


def references_missing_attachment(question: str) -> bool:
    return bool(MISSING_ATTACHMENT.search(question) or _SCHEDULE_REF.search(question))
