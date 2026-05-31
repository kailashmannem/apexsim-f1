import os
import modal

# Define the Modal Image
# Install all dependencies from our repository's requirements.txt
image = modal.Image.debian_slim(python_version="3.12").pip_install_from_requirements("requirements.txt")

# Define a persistent volume to act as the FastF1 cache
# This ensures that gigabytes of telemetry data are not re-downloaded across cold starts
volume = modal.Volume.from_name("apexsim-f1-cache", create_if_missing=True)

# Define the Modal App
app = modal.App("apexsim-backend")

# Define the ASGI endpoint
@app.function(
    image=image,
    volumes={"/app/f1_cache": volume},
    secrets=[
        # Requires the user to create a secret named 'watsonx-secret' in the Modal dashboard
        modal.Secret.from_name("watsonx-secret", required_keys=["WATSONX_API_KEY", "WATSONX_PROJECT_ID", "WATSONX_URL"])
    ],
    # Give the function enough timeout for heavy F1 telemetry downloads on a cold cache
    timeout=300, 
    # Allocate enough memory for Pandas
    memory=1024,
)
@modal.asgi_app()
def fastapi_endpoint():
    # Set the FASTF1_CACHE_DIR environment variable to point to our mounted persistent volume
    os.environ["FASTF1_CACHE_DIR"] = "/app/f1_cache"
    
    # Import our FastAPI app only when the container starts (after the volume is mounted)
    from backend.api import app as fastapi_app
    return fastapi_app
