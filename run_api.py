"""Quick-start: run FastAPI server (development)."""

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
