from fastapi import FastAPI

from .routers import chapters, manga

app = FastAPI(
    title="Manga Tracker API",
    description="REST API over the manga_tracker staging schema.",
    version="0.1.0",
)

app.include_router(manga.router)
app.include_router(chapters.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
