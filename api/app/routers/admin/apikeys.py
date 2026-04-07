from fastapi import APIRouter

router = APIRouter()


@router.get('/apikeys')
async def apikeys():
    return {}
