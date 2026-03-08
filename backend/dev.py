"""Development server launcher — excludes *.db from file watcher."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8899,
        reload=True,
        reload_excludes=["*.db", "*.db-journal", "*.db-wal", "uploads/*"],
    )
