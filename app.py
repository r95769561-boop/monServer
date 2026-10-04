import os
import uvicorn
from main import app as fastapi_app

# Gradio Integration for 100% Free Hugging Face Spaces (Zero-Card, No Paid Plan)
try:
    import gradio as gr

    with gr.Blocks(title="MON Control Server", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            """
            # ⚡ Microcontroller Overlay Network (MON)
            ### Zero-Trust P2P & End-to-End Encrypted Control Server

            The backend API, WebSockets, and P2P signaling are **ONLINE**.

            👉 **[Click Here to Open the MON Mobile / Web App Dashboard](/app/)**

            ---
            ### Service Endpoints
            - **Web & Mobile App**: [`/app/`](/app/)
            - **Health Check**: [`/health`](/health)
            - **Device WebSocket**: `wss://<host>/ws/device/{device_id}`
            - **Browser WebSocket**: `wss://<host>/ws/browser`
            - **Encrypted Relay**: `wss://<host>/relay/{session_id}/...`
            """
        )

    # Mount Gradio onto the existing FastAPI application
    app = gr.mount_gradio_app(fastapi_app, demo, path="/")
except Exception as e:
    # Graceful fallback if Gradio is not installed
    app = fastapi_app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
