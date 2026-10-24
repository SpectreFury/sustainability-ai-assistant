from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.answers import router as answers_router
from routers.auth import router as auth_router
from routers.documents import router as documents_router
from routers.evaluations import router as evaluations_router
from routers.financial_year import router as financial_year_router


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(answers_router)
app.include_router(financial_year_router)
app.include_router(evaluations_router)
