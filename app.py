import os
import spaces
from huggingface_hub import hf_hub_download
import server

# Satisfies the ZeroGPU startup watchdog
@spaces.GPU
def _init_gpu():
    pass

DB_PATH = "prices.db"

if not os.path.exists(DB_PATH):
    print("Downloading prices.db from dataset VicoWho/data...")
    DB_PATH = hf_hub_download(
        repo_id="VicoWho/data",
        repo_type="dataset",
        filename="prices.db",
        token=os.environ.get("HF_TOKEN")
    )
    print(f"Database ready at: {DB_PATH}")

if __name__ == "__main__":
    server.main(["--host", "0.0.0.0", "--port", "7860", "--db", DB_PATH])