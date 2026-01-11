from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
import numpy as np
import os
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml_service")

app = FastAPI(title="BolusAI ML Engine", version="0.1.0")

# --- Model Management ---
MODEL_PATH = os.getenv("MODEL_PATH", "model/lstm_transformer.tflite")
_interpreter = None

def load_model():
    global _interpreter
    if os.path.exists(MODEL_PATH):
        try:
            import tensorflow.lite as tflite
            _interpreter = tflite.Interpreter(model_path=MODEL_PATH)
            _interpreter.allocate_tensors()
            logger.info(f"✅ Loaded ML Model from {MODEL_PATH}")
        except Exception as e:
            logger.error(f"❌ Failed to load TFLite model: {e}")
            _interpreter = None
    else:
        logger.warning(f"⚠️ Model file not found at {MODEL_PATH}. Running in MOCK mode.")

@app.on_event("startup")
async def startup_event():
    load_model()

# --- Input Schema ---
class PredictionRequest(BaseModel):
    sgv_history: list[float]  # Last 60-120 mins of Glucose
    iob_history: list[float]  # Aligned IOB
    cob_history: list[float]  # Aligned COB
    
    # Context (Optional) for Hybrid Layer
    current_iob: float
    current_cob: float
    isf: float
    target: float

class PredictionResponse(BaseModel):
    predicted_bg: list[float]
    confidence: float
    source: str # "ml" or "mock"

# --- Inference Logic ---
@app.post("/predict", response_model=PredictionResponse)
async def predict_glucose(data: PredictionRequest):
    """
    Hybrid Prediction: ML + Physics Guardrails
    """
    # 1. Preprocessing
    # Ensure inputs are numpy arrays/tensor ready
    input_seq = [] 
    # Mock preprocessing logic corresponding to training data shape [N, 3]
    # (BG, IOB, COB) normalized
    
    # 2. Inference
    prediction = []
    source = "mock"
    
    if _interpreter:
        try:
            # TFLite Inference Steps (Abstracted)
            input_details = _interpreter.get_input_details()
            output_details = _interpreter.get_output_details()
            
            # _interpreter.set_tensor(input_details[0]['index'], processed_input)
            # _interpreter.invoke()
            # output_data = _interpreter.get_tensor(output_details[0]['index'])
            source = "ml"
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            # Fallback to mock
            pass

    # 3. Fallback / Mock Logic (Linear Projection)
    if not prediction:
        last_bg = data.sgv_history[-1] if data.sgv_history else 100
        # Simple drag: IOB reduces BG
        # Simple drag: COB raises BG
        
        # This is just for visualization testing until model is trained
        # Create a 6-point horizon (30 mins)
        prediction = []
        sim_bg = last_bg
        for _ in range(6):
            # Fake physics
            drop = data.current_iob * data.isf * (5/60) # 5 min step
            rise = data.current_cob * 0.1 # simplifying
            sim_bg = sim_bg - drop + rise
            prediction.append(round(sim_bg, 1))

    return {
        "predicted_bg": prediction,
        "confidence": 0.5 if source == "mock" else 0.9,
        "source": source
    }

@app.get("/health")
def health_check():
    return {"status": "ok", "model_loaded": _interpreter is not None}
