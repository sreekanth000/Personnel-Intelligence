import asyncio
import json
import uuid
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from core.db import DuckDBWorldModelStore
from core.models import Entity, EntityType, Relationship, OriginType, Provenance


# --- Models ---
class ReadinessAssessment(BaseModel):
    subject_id: str
    readiness_type: str
    state: str = "evaluating"  # e.g. at_risk, ready, evaluating
    due_at: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    suggested_actions: List[str] = Field(default_factory=list)
    urgency: str = "Low"
    fingerprint: str = ""
    next_check_at: Optional[str] = None
    title: str = ""
    message: str = ""


# --- Components ---


class CommitmentDetector:
    def __init__(self, db: DuckDBWorldModelStore):
        self.db = db

    def get_upcoming_commitments(self, days_ahead: int = 14) -> List[Entity]:
        with self.db._get_connection() as conn:
            now = datetime.utcnow()
            future = now + timedelta(days=days_ahead)

            # Fetch Events, Tasks, Commitments, Decisions, ProjectMilestones, and unpaid Bills
            query = """
                SELECT id, type, status, properties, source, confidence, updated_time, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance, aliases, canonical_id, identifiers
                FROM entities 
                WHERE (
                    (type IN ('Event', 'Meeting', 'Session', 'Workshop', 'Task', 'Commitment', 'Decision', 'ProjectMilestone')
                     AND COALESCE(valid_from, occurred_at) > ?
                     AND COALESCE(valid_from, occurred_at) < ?)
                    OR (type = 'Bill' AND COALESCE(json_extract_string(properties, '$.status'), 'unpaid') = 'unpaid')
                    OR type = 'BankAccount'
                )
                AND (status IS NULL OR status != 'Merged')
            """
            rows = conn.execute(query, (now.isoformat(), future.isoformat())).fetchall()
            return [self.db._row_to_entity(conn, row) for row in rows]

    def get_commitment(self, entity_id: str) -> Optional[Entity]:
        with self.db._get_connection() as conn:
            row = conn.execute(
                "SELECT id, type, status, properties, source, confidence, updated_time, valid_from, valid_to, observed_at, occurred_at, last_confirmed_at, timezone, recurrence, provenance, aliases, canonical_id, identifiers FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            return self.db._row_to_entity(conn, row)


class EvidenceRetriever:
    def __init__(self, db: DuckDBWorldModelStore, vector_store=None):
        self.db = db
        self.vector_store = vector_store

    async def get_evidence(self, commitment: Entity, policy: dict) -> dict:
        evidence = {}
        with self.db._get_connection() as conn:
            organization = commitment.properties.get("organization", "Unknown")
            topics = commitment.properties.get("topics", [])
            evidence["topic_context"] = topics
            evidence["organization"] = organization

            reqs = policy.get("evidence_required", [])

            if "presentation_or_notes" in reqs:
                # Check for linked presentations directly via RELATIONSHIPS
                presentations_query = """
                    SELECT e.id,
                           COALESCE(json_extract_string(e.properties, '$.name'), json_extract_string(e.properties, '$.title')) as doc_name,
                           json_extract_string(e.properties, '$.filepath') as file_path
                    FROM entities e
                    JOIN relationships r ON e.id = r.target_id
                    WHERE r.source_id = ? AND e.type IN ('Document', 'File')
                """
                presentations = conn.execute(
                    presentations_query, (commitment.id,)
                ).fetchall()
                linked_presentation = next(
                    (
                        p
                        for p in presentations
                        if any(
                            ext in (p[1] or "").lower()
                            for ext in [
                                ".pptx",
                                ".key",
                                "slide",
                                "presentation",
                                ".pdf",
                            ]
                        )
                    ),
                    None,
                )

                if linked_presentation:
                    evidence["presentation_or_notes"] = linked_presentation[0]
                else:
                    # Semantic / Organization fallback
                    if organization != "Unknown":
                        org_pattern = f"%{organization}%"
                        semantic_query = """
                            SELECT id,
                                   COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) as doc_name,
                                   json_extract_string(properties, '$.filepath') as file_path
                            FROM entities
                            WHERE type IN ('Document', 'File')
                              AND COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE ?
                              AND (
                                  COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE '%.pptx' OR
                                  COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE '%.key' OR
                                  COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE '%slide%' OR
                                  COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE '%presentation%' OR
                                  COALESCE(json_extract_string(properties, '$.name'), json_extract_string(properties, '$.title')) ILIKE '%.pdf' OR
                                  json_extract_string(properties, '$.extension') IN ('.pptx', '.key', '.pdf')
                              )
                            LIMIT 1
                        """
                        semantic_docs = conn.execute(
                            semantic_query, (org_pattern,)
                        ).fetchall()
                        if semantic_docs:
                            evidence["presentation_or_notes"] = semantic_docs[0][0]
                            evidence["presentation_needs_link"] = True

                    # Check Vector Store if not found via DuckDB
                    if (
                        "presentation_or_notes" not in evidence
                        and (topics or organization != "Unknown")
                        and self.vector_store
                    ):
                        search_str = (
                            f"{organization} {' '.join(topics)} presentation slides"
                        )
                        try:
                            semantic_results = await self.vector_store.search(
                                search_str, top_k=5
                            )
                            # semantic_results is List[Entity] for ChromaVectorStore
                            if semantic_results and isinstance(semantic_results, list):
                                for ent in semantic_results:
                                    name = ent.properties.get("name", "").lower()
                                    title_val = ent.properties.get("title", "").lower()
                                    ext = ent.properties.get("extension", "").lower()

                                    if (
                                        ext in (".pptx", ".key", ".pdf")
                                        or "slide" in name
                                        or "presentation" in name
                                        or "slide" in title_val
                                        or "presentation" in title_val
                                    ):
                                        evidence["presentation_or_notes"] = ent.id
                                        evidence["presentation_needs_link"] = True
                                        break
                        except Exception as e:
                            print(
                                f"[EvidenceRetriever] Vector store search failed: {e}"
                            )

            # Generic fallback for other evidence types (mock implementations for now)
            if "agenda" in reqs:
                if commitment.properties.get("agenda") or commitment.properties.get(
                    "description"
                ):
                    evidence["agenda"] = "found_in_properties"
            if "attendees" in reqs:
                if commitment.properties.get("attendees"):
                    evidence["attendees"] = "found_in_properties"
            if "deliverable_file_or_link" in reqs:
                # Stub
                pass
            if "matching_payment_transaction" in reqs:
                bill_amount = commitment.properties.get("bill_amount")
                bill_date_str = commitment.properties.get("bill_date") or (
                    commitment.created_time.isoformat()
                    if hasattr(commitment, "created_time")
                    else None
                )
                account_last4 = commitment.properties.get("account_last4")
                issuer = commitment.properties.get("issuer")

                try:
                    if bill_date_str:
                        bill_date = datetime.fromisoformat(
                            bill_date_str.replace("Z", "+00:00")
                        )
                    else:
                        bill_date = datetime.utcnow()
                except:
                    bill_date = datetime.utcnow()

                transactions = conn.execute(
                    "SELECT id, properties FROM entities WHERE type='FinancialTransaction'"
                ).fetchall()

                matched_txn = None
                uncertain_txn = None

                for row in transactions:
                    txn_id = row[0]
                    txn_props = (
                        json.loads(row[1]) if isinstance(row[1], str) else row[1]
                    )

                    # Rule: transaction_after_bill
                    txn_date_str = txn_props.get("occurred_at")
                    if not txn_date_str:
                        continue
                    try:
                        txn_date = datetime.fromisoformat(
                            txn_date_str.replace("Z", "+00:00")
                        )
                        if txn_date < bill_date:
                            continue
                    except:
                        continue

                    # Rule: amount_greater_than_or_equal_to_bill
                    txn_amount = txn_props.get("amount")
                    if bill_amount is None or txn_amount is None:
                        continue
                    try:
                        if (
                            float(txn_amount) < float(bill_amount) * 0.99
                        ):  # 1% tolerance
                            continue
                    except:
                        continue

                    # Rule: same_account_or_card
                    is_same_account = False
                    txn_last4 = txn_props.get("account_last4")
                    if account_last4 and txn_last4 and account_last4 == txn_last4:
                        is_same_account = True

                    # Rule: payment_related_description
                    counterparty = txn_props.get("counterparty", "")
                    ref = txn_props.get("reference_number", "")
                    desc_matches = False
                    if issuer and issuer.lower() in counterparty.lower():
                        desc_matches = True
                    if issuer and issuer.lower() in ref.lower():
                        desc_matches = True
                    if txn_props.get("transaction_type") == "bill_payment":
                        desc_matches = True

                    if is_same_account and desc_matches:
                        matched_txn = txn_id
                        evidence["matching_payment_transaction"] = matched_txn
                        evidence["matching_payment_amount"] = txn_amount
                        evidence["matching_payment_ref"] = ref
                        break
                    elif (is_same_account or desc_matches) or (
                        float(txn_amount) == float(bill_amount)
                    ):
                        uncertain_txn = txn_id
                        evidence["uncertain_payment_amount"] = txn_amount

                if not matched_txn and uncertain_txn:
                    evidence["uncertain_payment_transaction"] = uncertain_txn

        return evidence


class ReadinessEvaluator:
    def __init__(self, policies: List[dict]):
        self.policies = policies

    def evaluate(
        self, commitment: Entity, evidence: dict
    ) -> Optional[ReadinessAssessment]:
        # Determine which policy applies
        applied_policy = None
        for policy in self.policies:
            applies = policy.get("applies_when", {})
            if commitment.type.value in applies.get("entity_type", []):
                # Check requirements
                req_prep = applies.get("requires_preparation")
                if (
                    req_prep is not None
                    and commitment.properties.get("requires_preparation") != req_prep
                ):
                    continue
                has_loc = applies.get("has_location")
                if (
                    has_loc is not None
                    and (commitment.properties.get("location") is not None) != has_loc
                ):
                    continue
                req_status = applies.get("status")
                if (
                    req_status is not None
                    and commitment.properties.get("status") != req_status
                ):
                    continue
                name_not_contains = applies.get("name_not_contains", [])
                if name_not_contains:
                    c_name = (
                        commitment.properties.get("name")
                        or commitment.properties.get("title")
                        or ""
                    )
                    if any(
                        bad_word.lower() in c_name.lower()
                        for bad_word in name_not_contains
                    ):
                        continue
                applied_policy = policy
                break

        if not applied_policy:
            return None

        # Evaluate urgency
        ev_time = commitment.valid_from or commitment.occurred_at
        if isinstance(ev_time, str):
            try:
                ev_time = datetime.fromisoformat(ev_time.replace("Z", "+00:00"))
            except:
                return None

        now = datetime.utcnow()
        if ev_time.tzinfo:
            now = datetime.now(ev_time.tzinfo)

        time_to_event = ev_time - now
        hours_to_event = time_to_event.total_seconds() / 3600

        if hours_to_event < 0 and commitment.type.value not in ["Bill", "BankAccount"]:
            return None

        windows = applied_policy.get("urgency_windows", {})
        urgency = "Low"
        if commitment.type.value == "BankAccount":
            urgency = "Low"  # Will update later
        elif hours_to_event < windows.get("urgent_hours_before", 24):
            urgency = "Urgent"
        elif hours_to_event < windows.get("high_hours_before", 72):
            urgency = "High"
        elif time_to_event.days > 14 and commitment.type.value != "BankAccount":
            return None  # Ignore items > 14 days out

        assessment = ReadinessAssessment(
            subject_id=commitment.id,
            readiness_type=applied_policy["readiness_type"],
            due_at=ev_time.isoformat(),
            urgency=urgency,
            fingerprint=hashlib.md5(
                f"{commitment.id}_{applied_policy['readiness_type']}".encode()
            ).hexdigest(),
        )

        # Check evidence gaps dynamically
        reqs = applied_policy.get("evidence_required", [])
        missing_evidence = [r for r in reqs if r not in evidence]

        c_name = (
            commitment.properties.get("name")
            or commitment.properties.get("title")
            or commitment.type.value
        )

        if applied_policy.get("readiness_type") == "bill_payment_reconciliation":
            issuer = commitment.properties.get("issuer", "Unknown")
            amt = commitment.properties.get("bill_amount", "0")
            cur = commitment.properties.get("currency", "₹")
            due_str = commitment.properties.get("due_date", "Unknown date")

            if "matching_payment_transaction" in evidence:
                assessment.state = "ready"
                assessment.urgency = "Low"
                payment_amt = evidence.get("matching_payment_amount", amt)
                payment_ref = evidence.get("matching_payment_ref", "N/A")
                assessment.title = f"Paid: {issuer} Bill"
                assessment.message = f"{issuer} bill of {cur}{amt} appears paid on {due_str}. Matching payment: {cur}{payment_amt}, reference {payment_ref}."
            elif "uncertain_payment_transaction" in evidence:
                assessment.state = "at_risk"
                payment_amt = evidence.get("uncertain_payment_amount", amt)
                assessment.title = f"Action Required: Verify {issuer} Payment"
                assessment.message = f"A {cur}{payment_amt} credit was found after the bill, but it could not be linked to the {issuer} account. Please verify."
                assessment.gaps.append("verify payment linkage")
                assessment.suggested_actions.append(
                    "Verify if recent transaction matches bill"
                )
            else:
                assessment.state = "at_risk"
                assessment.title = f"Action Required: Pay {issuer} Bill"
                assessment.message = f"{issuer} bill of {cur}{amt} is due on {due_str}."
                assessment.gaps.append("Missing payment transaction")
                assessment.suggested_actions.append("Pay bill")
        elif applied_policy.get("readiness_type") == "low_balance_alert":
            bank_name = commitment.properties.get("bank_name", "Unknown Bank")
            last4 = commitment.properties.get("account_last4", "XXXX")
            balance = commitment.properties.get("balance", 0)
            try:
                balance = float(balance)
            except:
                balance = 0
            curr = commitment.properties.get("currency", "₹")
            threshold = applied_policy.get("balance_threshold", 10000)

            if balance < threshold:
                assessment.state = "at_risk"
                assessment.urgency = "High"
                assessment.title = f"Low Balance: {bank_name}"
                assessment.message = f"{bank_name} account ending in {last4} has a low balance of {curr}{balance:,.2f}."
                assessment.gaps.append(f"Balance below {curr}{threshold}")
                assessment.suggested_actions.append(
                    "Transfer funds to maintain minimum balance"
                )
            else:
                assessment.state = "ready"
                assessment.urgency = "Low"
                assessment.title = f"Healthy Balance: {bank_name}"
                assessment.message = f"{bank_name} account ending in {last4} has a balance of {curr}{balance:,.2f}."
        elif missing_evidence:
            assessment.state = "at_risk"
            for m in missing_evidence:
                assessment.gaps.append(f"Missing {m.replace('_', ' ')}")
            assessment.suggested_actions.append(
                f"Prepare missing items: {', '.join(missing_evidence).replace('_', ' ')}"
            )
            assessment.title = f"Action Required: Prep for {c_name}"

            day_str = (
                "today" if time_to_event.days == 0 else f"in {time_to_event.days} days"
            )
            assessment.message = f"{c_name} is {day_str}; missing {', '.join(missing_evidence).replace('_', ' ')}."
        else:
            assessment.state = "ready"
            assessment.title = f"Ready: {c_name}"
            day_str = (
                "today" if time_to_event.days == 0 else f"in {time_to_event.days} days"
            )
            assessment.message = (
                f"{c_name} is {day_str}. All required evidence is linked."
            )
            assessment.urgency = "Low"  # Ready means low urgency

        return assessment


class InsightLifecycleManager:
    def __init__(self, db: DuckDBWorldModelStore):
        self.db = db

    async def link_evidence(self, subject_id: str, evidence_id: str):
        prov = Provenance(
            source_connector="AutonomousReadinessIntelligence",
            origin_type=OriginType.INFERRED,
        )
        rel = Relationship(
            target_entity_id=evidence_id,
            relationship_type="ATTACHED_TO",
            provenance=prov,
        )
        await self.db.upsert_relationship(subject_id, rel)

    async def manage_insight(self, assessment: ReadinessAssessment):
        insight_id = assessment.fingerprint
        with self.db._get_connection() as conn:
            existing_insight = conn.execute(
                "SELECT properties, status FROM entities WHERE id = ? AND type='Insight'",
                (insight_id,),
            ).fetchone()

        # 1. Persist the ReadinessAssessment evaluation entity to the world model to retain history
        prov = Provenance(
            source_connector="AutonomousReadinessIntelligence",
            origin_type=OriginType.INFERRED,
        )
        assessment_entity = Entity(
            id=f"assessment_{uuid.uuid4()}",
            type=EntityType("ReadinessAssessment"),
            properties=assessment.dict(),
            provenance=prov,
            source="AutonomousReadinessIntelligence",
        )
        await self.db.upsert_entity(assessment_entity)

        # Link assessment to the subject
        rel = Relationship(
            target_entity_id=assessment.subject_id,
            relationship_type="ASSESSES",
            provenance=prov,
        )
        await self.db.upsert_relationship(assessment_entity.id, rel)

        # 2. Manage the Insight (user-facing)
        insight_doc = {
            "event_id": assessment.subject_id,
            "name": assessment.title,  # UI expects name
            "message": assessment.message,
            "severity": assessment.urgency,
            "fingerprint": assessment.fingerprint,
            "due_at": assessment.due_at,
            "state": assessment.state,
            "gaps": assessment.gaps,
            "suggested_actions": assessment.suggested_actions,
        }

        if not existing_insight:
            insight_entity = Entity(
                id=insight_id,
                type=EntityType("Insight"),
                properties=insight_doc,
                provenance=prov,
                source="AutonomousReadinessIntelligence",
            )
            await self.db.upsert_entity(insight_entity)
            print(
                f"[InsightManager] Created new insight: {insight_doc['name']} ({assessment.urgency})"
            )
        else:
            existing_props = (
                json.loads(existing_insight[0])
                if isinstance(existing_insight[0], str)
                else existing_insight[0]
            )
            existing_status = existing_insight[1]

            if (
                existing_props.get("state") == "dismissed"
                or existing_status == "Deleted"
            ):
                return  # User handled it

            needs_update = False

            # Check for transitions (both up and down)
            sev_levels = {"Low": 1, "Medium": 2, "High": 3, "Urgent": 4}
            old_sev = sev_levels.get(existing_props.get("severity", "Low"), 1)
            new_sev = sev_levels.get(assessment.urgency, 1)

            if new_sev != old_sev:
                existing_props["severity"] = assessment.urgency
                needs_update = True

            old_state = existing_props.get("state")
            if assessment.state != old_state:
                existing_props["state"] = assessment.state
                needs_update = True
                if assessment.state == "ready":
                    existing_props["state"] = "resolved"
                    print(f"[InsightManager] Resolved insight: {insight_doc['name']}")

            if existing_props.get("message") != insight_doc["message"]:
                existing_props["message"] = insight_doc["message"]
                needs_update = True

            if existing_props.get("name") != insight_doc["name"]:
                existing_props["name"] = insight_doc["name"]
                needs_update = True

            # Update gaps and actions just in case
            if existing_props.get("gaps") != insight_doc["gaps"]:
                existing_props["gaps"] = insight_doc["gaps"]
                needs_update = True

            if needs_update:
                insight_entity = Entity(
                    id=insight_id,
                    type=EntityType("Insight"),
                    properties=existing_props,
                    provenance=prov,
                    source="AutonomousReadinessIntelligence",
                )
                await self.db.upsert_entity(insight_entity)
                print(f"[InsightManager] Updated insight: {insight_doc['name']}")


class AutonomousReadinessIntelligence:
    """The orchestrator that replaces the monolithic ProactiveReadinessEngine."""

    def __init__(
        self,
        db: DuckDBWorldModelStore,
        vector_store=None,
        policies_path="core/policies.json",
    ):
        self.db = db
        self._running = False

        # Load policies from JSON
        self.policies = []
        if os.path.exists(policies_path):
            try:
                with open(policies_path, "r") as f:
                    self.policies = json.load(f)
            except Exception as e:
                print(
                    f"[AutonomousReadinessIntelligence] Failed to load policies from {policies_path}: {e}"
                )
        else:
            print(
                f"[AutonomousReadinessIntelligence] Policies file not found at {policies_path}"
            )

        self.detector = CommitmentDetector(db)
        self.retriever = EvidenceRetriever(db, vector_store)
        self.evaluator = ReadinessEvaluator(self.policies)
        self.lifecycle = InsightLifecycleManager(db)

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    async def handle_new_entity(self, event):
        raw_data = event.raw_data
        if not raw_data or "entity_id" not in raw_data:
            return
        entity_id = raw_data["entity_id"]
        asyncio.create_task(self.evaluate_commitment(entity_id))

    async def run_loop(self, interval_seconds: int = 900):
        self.start()
        print("[AutonomousReadinessIntelligence] Started background loop.")
        while self._running:
            try:
                commitments = await asyncio.get_running_loop().run_in_executor(
                    None, self.detector.get_upcoming_commitments
                )
                for commitment in commitments:
                    await self.evaluate_commitment(commitment.id, commitment)
            except Exception as e:
                print(f"[AutonomousReadinessIntelligence] Error in loop: {e}")
            await asyncio.sleep(interval_seconds)

    async def evaluate_commitment(
        self, entity_id: str, commitment: Optional[Entity] = None
    ):
        if not commitment:
            commitment = await asyncio.get_running_loop().run_in_executor(
                None, self.detector.get_commitment, entity_id
            )

        if not commitment:
            return

        # Simple pre-check to find applicable policy before heavy lifting
        applied_policy = None
        for policy in self.evaluator.policies:
            applies = policy.get("applies_when", {})
            if commitment.type.value in applies.get("entity_type", []):
                req_prep = applies.get("requires_preparation")
                if (
                    req_prep is not None
                    and commitment.properties.get("requires_preparation") != req_prep
                ):
                    continue
                has_loc = applies.get("has_location")
                if (
                    has_loc is not None
                    and (commitment.properties.get("location") is not None) != has_loc
                ):
                    continue
                applied_policy = policy
                break

        if not applied_policy:
            return

        evidence = await self.retriever.get_evidence(commitment, applied_policy)

        if evidence.get("presentation_needs_link") and evidence.get(
            "presentation_or_notes"
        ):
            await self.lifecycle.link_evidence(
                commitment.id, evidence["presentation_or_notes"]
            )

        assessment = self.evaluator.evaluate(commitment, evidence)
        if assessment:
            await self.lifecycle.manage_insight(assessment)
