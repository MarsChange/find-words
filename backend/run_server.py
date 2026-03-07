"""PyInstaller entry point for the FindWords backend server."""

import multiprocessing
import sys
import os

# When running as a PyInstaller bundle, adjust the base path
if getattr(sys, 'frozen', False):
    # Running in PyInstaller bundle
    _bundle_dir = os.path.dirname(sys.executable)
else:
    _bundle_dir = os.path.dirname(os.path.abspath(__file__))

# Ensure the app package is importable
sys.path.insert(0, _bundle_dir)


def main():
    # Import uvicorn and the FastAPI app inside main() so that
    # multiprocessing worker processes (which re-run this script on
    # Windows/spawn) never import or start the server.
    import uvicorn
    from app.main import app as application

    host = os.environ.get("FINDWORDS_HOST", "127.0.0.1")
    port = int(os.environ.get("FINDWORDS_PORT", "8000"))

    uvicorn.run(
        application,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    # On Windows (spawn), ProcessPoolExecutor worker processes re-run
    # this entry point.  freeze_support() detects child workers and
    # routes them to the multiprocessing protocol instead of main().
    multiprocessing.freeze_support()
    main()
