# Product Requirements Document: FairFine FinTech (Fraud Accountability Layer)

## 1. Executive Summary
FairFine FinTech is an adversarial multi-agent auditing system designed to sit between aggressive fraud detection engines and customer-facing actions (like account freezes). By repurposing a proven traffic-violation audit architecture, this system provides a "calibrated second opinion" that allows banks to flag fraud more aggressively while drastically reducing wrongful blocks through high-fidelity, automated adversarial review.

## 2. Problem Statement
Financial institutions face a "False Positive Paradox":
1. **The Defrauded:** Victims lose money because detection thresholds are tuned conservatively to avoid customer friction.
2. **The Wrongly Blocked:** Legitimate customers are "harmed" by frozen accounts and declined transactions when thresholds are lowered, leading to churn and brand damage.
Current systems lack a high-speed, intelligent "defense attorney" for the customer that can validate a fraud flag in real-time before the block is executed.

## 3. Goals & Objectives
*   **Primary Goal:** Enable "Aggressive Detection, Precise Action."
*   **Objective:** Reduce false-positive account freezes by 40% without increasing fraud slippage.
*   **Success Criteria:** A demo-ready system that can ingest a "suspicious" transaction and correctly veto a wrongful block based on context and regulatory RAG.

## 4. Target Users / Stakeholders
*   **Fraud Ops Analyst:** Needs to understand *why* the auditor overruled the primary detector.
*   **Affected Customer:** Needs a plain-language explanation of why a transaction was temporarily held or why their account remains safe.
*   **Bank Executive:** Needs to see the "Comparison Panel" showing the delta between the old threshold-only system and the FairFine audit layer.

## 5. Functional Requirements
### Core Agentic Workflow (Domain Mapped)
*   **IngestAgent:** Accepts JSON payloads containing transaction details (amount, location, merchant) and account history.
*   **PerceptionStage:**
    *   **TransactionAnalyzer (formerly Detector):** Analyzes transaction metadata for anomalies.
    *   **MerchantProfiler (formerly Plate):** Checks merchant reputation against mocked databases.
*   **MemoryAgent:** Performs a "Duplicate Sweep" (is this a double-tap?) and "Statute RAG" (queries mocked RBI fraud circulars and card-network rules).
*   **AuditorAgent:** Conducts an adversarial review of the primary fraud flag. It must generate a **Calibrated Trust Score**.
*   **VerdictRouter:** Routes to **BLOCK** (Trust >= 0.90), **REVIEW** (0.60 - 0.89), or **ALLOW** (< 0.60).
*   **LedgerAgent:** Records the audit trail in a tamper-evident hash chain for compliance.

### Features
*   **Plain-Language Explanations:** Generates customer-facing justifications in 4 languages.
*   **Comparison Panel:** A dashboard showing "What would have happened" (e.g., "Old system would have blocked this legitimate traveler").
*   **PII Redaction:** Automated masking of sensitive account numbers before LLM processing.

## 6. Non-Functional Requirements
*   **Latency:** Audit completion in < 2 seconds (optimized for Gemini 2.5 Flash).
*   **Explainability:** Every "Veto" must cite a specific reason or regulatory rule.
*   **Scalability:** Stateless FastAPI deployment on Cloud Run to handle burst transaction volume.
*   **Reliability:** Strict `output_schema` enforcement for all LLM agents to prevent downstream parsing errors.

## 7. System Architecture Overview
The system reuses the **FairFine Multi-Agent Tree**:
1.  **Input:** Transaction JSON.
2.  **Processing:** Parallel analysis by Transaction & Merchant agents.
3.  **Contextualization:** RAG-augmented history and regulatory check.
4.  **Adversarial Audit:** The AuditorAgent attempts to "disprove" the fraud flag.
5.  **Output:** Final Verdict + Hash Chain Entry + UI Update.

## 8. Tech Stack
*   **Orchestration:** Google ADK (Agent Development Kit).
*   **LLM:** Gemini 2.5 Flash (via Vertex AI).
*   **Backend:** FastAPI, Python 3.11.
*   **Frontend:** Next.js, Tailwind CSS (deployed on Vercel).
*   **Infrastructure:** Google Cloud Run.
*   **Data:** Mocked JSON for Merchant/Account reputation and RBI circulars.

## 9. Data Requirements
*   **Input Schema:** `{ transaction_id, account_id, amount, merchant_id, location, timestamp, account_history: [] }`.
*   **RAG Corpus:** Mocked markdown files containing RBI (Reserve Bank of India) fraud guidelines and standard chargeback codes.
*   **Reputation Mock:** A simple lookup table for "High Risk" vs "Trusted" merchants.

## 10. API Specifications
*   `POST /api/v1/ingest`: Receives transaction data.
*   `GET /api/v1/audit/{id}`: Returns current audit status and agent logs.
*   `GET /api/v1/verdict/{id}`: Returns final BLOCK/REVIEW/ALLOW decision and the "Comparison" data.

## 11. Security Requirements
*   **Redaction:** IngestAgent must strip or mask PII (e.g., full card numbers) before passing data to the PerceptionStage.
*   **Integrity:** LedgerAgent creates a SHA-256 hash of the audit log to ensure the decision wasn't tampered with post-facto.

## 12. Deployment & Infrastructure
*   **CI/CD:** GitHub Actions to Vercel (Frontend) and Cloud Run (Backend).
*   **Environment:** Production-ready FastAPI container.

## 13. Success Metrics
*   **False Positive Rate (FPR):** Measured against the "Comparison Panel."
*   **Audit Speed:** Time from Ingest to Verdict.
*   **Veto Accuracy:** Qualitative review of the AuditorAgent's reasoning.

## 14. Timeline & Milestones (2-Hour Hackathon Sprint)
*   **0:00 - 0:30:** Update Agent Prompts (Domain mapping from Traffic to FinTech).
*   **0:30 - 1:00:** Mock Data Generation (RBI Circulars + Transaction History JSON).
*   **1:00 - 1:30:** UI Refactor (Update "Violation" dashboard to "Fraud Ops" dashboard).
*   **1:30 - 2:00:** Demo Polishing & Comparison Panel logic.

## 15. Open Questions & Risks
*   **Risk:** Gemini 2.5 Flash latency might exceed 2 seconds for deep RAG. *Mitigation: Use concise mock corpus.*
*   **Question:** Should the "Review" verdict trigger a real-time SMS? *Decision: Out of scope for demo; mock the notification.*

---

## 16. Appendix: Demo Strategy (Requested)

### The Non-Obvious Insight
Banks currently treat fraud detection as a single-pass classification problem, leading to "safe" but high-friction thresholds. By introducing an **adversarial auditor** that specifically looks for reasons to *veto* a block, we decouple detection from action. This allows the primary detector to be hyper-sensitive (catching more fraud) while the auditor ensures customer experience isn't sacrificed.

### Scope: IN vs OUT
*   **IN:** Full agentic flow, RAG-based vetoes, Comparison Panel, Plain-language explanation.
*   **OUT:** Real bank API integration, actual PII handling, multi-user auth, real-time SMS gateways.

### Decision Rules: The Five Vetoes
The AuditorAgent must independently veto a "BLOCK" if any of these are true:
1.  **Historical Consistency:** The user has shopped at this merchant or category before.
2.  **Geographic Feasibility:** The transaction location matches the user's recent "Allowed" travel/location data.
3.  **Regulatory Safe Harbor:** The transaction falls under specific RBI "low-risk" categories (e.g., small-value utility payments).
4.  **Merchant Legitimacy:** The merchant has a high reputation score despite the transaction size.
5.  **Behavioral Pattern:** The "suspicious" activity matches a known non-fraud pattern (e.g., annual subscription renewal).

### 4-Minute Demo Script
*   **0:00-1:00:** Show the "Comparison Panel." Explain that the "Old System" just blocked a $2,000 transaction because it was "out of pattern."
*   **1:00-2:00:** Trigger the FairFine Audit. Show the **PerceptionStage** identifying the merchant as a high-end hotel and the **MemoryAgent** finding a "Travel Notification" in the mocked RAG/History.
*   **2:00-3:00:** **The "Aha!" Moment:** The AuditorAgent issues a **VETO**. It explains: *"While the amount is high, the user is currently in London (verified by 2 previous small coffee shop transactions) and this is a reputable hotel. Blocking would cause high customer friction."*
*   **3:00-4:00:** Show the final verdict: **ALLOW**. Show the customer-facing explanation: *"We noticed an unusual high-value charge. We've verified this matches your travel pattern. No action needed."* Point to the "Fraud Prevented" vs "Wrongful Blocks Avoided" counter.