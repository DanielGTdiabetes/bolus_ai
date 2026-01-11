# Feasibility Study: Hybrid LSTM-Transformer (ML) vs. Physics Engine (OpenAPS)

## 1. Executive Summary
This document analyzes the feasibility, risks, and benefits of migrating the current **Physics-Based Forecast Engine** to a proposed **Hybrid Machine Learning (LSTM-Transformer)** model.

**Recommendation:** Adopt a **Phased "Shadow Mode" Implementation**.  
Do *not* replace the current engine immediately. ML models require extensive validation for safety-critical applications like insulin dosing. We should deploy the ML microservice to run in parallel, comparing its predictions against the Physics engine and real-world outcomes before giving it control.

---

## 2. Comparison Matrix

| Feature | Current: Physics Engine (OpenAPS/Techne) | Proposed: Hybrid ML (LSTM-Transformer) |
| :--- | :--- | :--- |
| **Core Logic** | Deterministic Math (Insulin/Carb Curves, Basal Profiles). | Statistical/Pattern Recognition (Neural Networks). |
| **Explainability** | **High**. "Predicted low because IOB > Carbs". | **Low**. "Predicted low because tensor weights activated". |
| **Adaptability** | Manual Tuning (ISF, CR). Heuristics (Autosens). | **Automatic**. Learns hidden factors (stress, sleep cycles, etc). |
| **Safety** | Proven OpenAPS logic. Predictable failure modes. | Risk of "Hallucination" on unseen data. Requires guardrails. |
| **Latency** | < 10ms (Instant CPU calc). | ~200-500ms (Model Inference + HTTP overhead). |
| **Infrastructure** | Integrated in monolith (Python). | Requires separate Microservice (TF/Keras heavy dependencies). |
| **Data Needs** | Current state + Settings. | Historical datasets (months of data) for training. |

---

## 3. Gap Analysis & Implementation Status (Updated Jan 2026)

We have successfully implemented the core infrastructure for the Hybrid ML integration.

### Phase 1: Data Pipeline (Implemented ✅)
*   **Status:** Active.
*   **Mechanism:** `app/bot/service.py` captures a snapshot of Glucose, IOB, COB, and Trends every 5 minutes during the standard job cycle.
*   **Storage:** Data is stored in the `ml_training_data` table (Postgres/NeonDB).

### Phase 2: Microservice Deployment (Implemented ✅)
*   **Status:** Deployed (Skeleton/Shadow Mode).
*   **Infrastructure:** A dedicated FastAPI microservice (`backend/ml_service`) has been created.
*   **Optimization:** Configured to use **TensorFlow Lite (TFLite)** to minimize RAM usage (<100MB) on Render.
*   **Current Logic:** Running in "Learning Mode" (Shadow). It collects call signatures and provides a mock visualization (linear projection) until the model is trained with real user data.

### Phase 3: Frontend Integration (Implemented ✅)
*   **Status:** Active in Beta.
*   **Visualization:** The `MainGlucoseChart.jsx` now displays a secondary **Emerald Dotted Line** representing the ML prediction.
*   **UX/Safety:** 
    *   Explicit labels: "🤖 Aprendiendo del usuario..." vs "✨ IA Híbrida Activa".
    *   Safety Disclaimer: "No usar para decisiones médicas".
    *   **Future Transition:** Once the system validates the ML model is ready (`ml_ready=True`), the legacy OpenAPS physics curve will be **automatically removed**, leaving the ML model as the sole reliable forecast.

---

## 4. Risks & Mitigations

### 1. The "Cold Start" Problem
*   **Mitigation Active:** The system defaults to "Learning Mode". The Frontend clearly indicates that the model is in its training phase. A mock curve facilitates UI testing without misleading the user.

### 2. Infrastructure Cost
*   **Mitigation Active:** Adopted **TFLite** architecture. The service is decoupled but lightweight.

### 3. Safety Criticality
*   **Mitigation Active:** The ML model is **read-only**. It does NOT feed into the Bolus Calculator logic, which remains purely physics-based (OpenAPS/Techne) for safety.

## 5. Decision & Next Steps
**Verdict:** Infrastructure is **Complete**.
**Next Steps:**
1.  **Wait** for ~2-4 weeks of data accumulation in `ml_training_data`.
2.  **Train** the LSTM-Transformer TFLite model using the collected dataset.
3.  **Deploy** the trained `.tflite` model to `backend/ml_service/model/`.
4.  **Activate** `ml_ready = True` in the backend. 
    *   *Result:* The OpenAPS curve will disappear, and the ML curve will become the primary visualization.
