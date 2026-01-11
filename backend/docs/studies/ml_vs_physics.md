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

## 3. Gap Analysis & Implementation Plan

To implement the users request, we need to build the following components which do not currently exist:

### Phase 1: Data Pipeline (The Foundation)
*Current Status:* We fetch data from Nightscout but discard it or use it ephemerally.
*Goal:* Create a robust training dataset.
1.  **Logging**: Enhance `app/bot/service.py` to log every 5-min cycle to `postgres` (or `neondb`).
2.  **Schema**: `timestamp`, `sgv`, `delta`, `trend`, `iob`, `cob`, `basal_rate`, `accelerometer` (if avail).
3.  **Export**: Script to dump DB to CSV for Colab training.

### Phase 2: Microservice Deployment (The Engine)
*Current Status:* Monolithic FastAPI app.
*Goal:* Lightweight ML Inference Service.
1.  **Stack**: Python 3.10 + `tensorflow-cpu` (to save RAM) + `fastapi`.
2.  **Hosting**: Render (Service B). Note: TF consumes ~500MB RAM, might require paid tier.
3.  **Model**:
    *   **Input**: Window of 60m-120m (CGB, IOB, COB).
    *   **Architecture**: 
        *   Layer 1: LSTM (Temporal dependencies).
        *   Layer 2: Multi-Head Attention (Transformer - Logic dependencies).
        *   Head: Dense Output (+30m, +60m prediction).
4.  **Guardrails (OpenAPS Overlay)**:
    *   The user correctly identified that ML needs safety.
    *   Logic: `Final_Pred = (ML_Pred * Weight) + (OpenAPS_Eventual * (1-Weight))`? 
    *   *Correction:* The user proposed finding `autosens` logic. Actually, standard practice is to **Clamp** the ML prediction within OpenAPS bounds (e.g., don't predict < 40 if OpenAPS says 120).

### Phase 3: Frontend Integration
*Current Status:* Chart.js receives one `forecast` array.
*Goal:* Multi-line visualization.
1.  **Backend Proxy**: The main API should fetch the ML prediction so the Frontend doesn't deal with CORS/Auth for a second service.
2.  **UI**: Show "Physics" (Solid Line) vs "AI Beta" (Dotted Line).

---

## 4. Risks & Mitigations

### 1. The "Cold Start" Problem
*Risk:* If a user is new, the LSTM has no personal data. General models (OhioT1DM) often perform poorly on individuals due to varying ISF/CR.
*Mitigation:* Use the Physics Engine as the "Prior" or fallback until 2 weeks of data are collected.

### 2. Infrastructure Cost
*Risk:* Running a TensorFlow instance 24/7 on Render is more expensive than a simple script.
*Mitigation:* Use **TFLite** (TensorFlow Lite) or ONNX Runtime to run the model within the *main* backend, avoiding a second service. This reduces RAM usage drastically (100MB vs 500MB).

### 3. Safety Criticality
*Risk:* Determining a Bolus based on a "Black Box" that might glitch.
*Mitigation:* **Never** allow the ML model to dispense insulin autonomously in V1. Use it only for *Forecast Visualization* (Advisory). Keep the Bolus Calculator logic tied to the Physics Engine.

## 5. Decision
**Verdict:** **Proceed with Phase 1 (Data Collection)** immediately. Pause Phase 2 until we have 1 month of clean data. 

The proposal is technically sound and represents the state-of-the-art (SOTA) in academic research, but requires a rigorous MLOps pipeline that BolusAI currently lacks.
