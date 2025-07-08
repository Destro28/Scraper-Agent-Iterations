# In phi3_server_api.py

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline, BitsAndBytesConfig
import logging

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global Model Loading ---
logger.info("Initializing local model... This may take a few minutes.")

model_id = "microsoft/phi-2" 

quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
)

llm_pipeline = pipeline(
    "text-generation",
    model=model_id,
    trust_remote_code=True,
    model_kwargs={
        "torch_dtype": torch.bfloat16,
        "quantization_config": quantization_config,
    },
    device_map="auto",
)

logger.info("Local model initialized successfully and ready to serve.")

# --- API Definition ---
app = FastAPI()

class HTMLPayload(BaseModel):
    html: str

@app.post("/generate_selectors")
async def generate_selectors(payload: HTMLPayload):
    try:
        logger.info("Received request to generate selectors.")
        
        # **FIX APPLIED HERE:**
        # Instead of using apply_chat_template, we build the prompt manually
        # in a format that phi-2 understands.
        prompt = (
            "Instruct: You are an expert web scraper assistant. Your task is to analyze HTML and identify CSS selectors "
            "for elements that likely lead to PDF files. You must return your findings as a single, raw JSON object "
            "with one key, 'selectors', which holds a list of these selector strings. "
            "Do not include any other text, explanations, or markdown.\n"
            f"HTML:\n```html\n{payload.html}\n```\n"
            "Output:"
        )
        
        outputs = llm_pipeline(
            prompt,
            max_new_tokens=1024,
            do_sample=False, 
            # Temperature is ignored when do_sample=False, so it can be removed, but it's not harmful.
        )
        
        # We get the raw generated text. For phi-2, we don't need to clean it like a chat model.
        generated_text = outputs[0]['generated_text']
        logger.info("Successfully generated response.")
        return {"result_text": generated_text}

    except Exception as e:
        logger.error(f"An internal error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Model processing failed: {e}")