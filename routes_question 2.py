# routes_question.py
from fastapi import APIRouter
router = APIRouter(prefix="/questions", tags=["Questions"])

# routes_debate.py already handles questions/options within debates
