import os
import sys
from pathlib import Path

import uvicorn


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), reload=os.getenv("RELOAD", "true").lower() == "true")

