from fastapi import FastAPI

from .routers import render, sign

app = FastAPI(debug=True)
app.include_router(render)
app.include_router(sign)


@app.get('/health')
async def health_check():
    return {'status': 'healthy'}
