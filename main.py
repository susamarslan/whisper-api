from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import tempfile
from tasks import transcribe_task, celery_app

app = FastAPI()

@app.post("/transcribe")
async def transcribe(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    language: str | None = Form(None),
    task: str = Form("transcribe"),
    temperature: float = Form(0.0),
    save: bool = Form(False),
    model_name: str = Form("base"),
    concurrency: int = Form(1)
):
    jobs = []

    if file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            while chunk := await file.read(8192):
                tmp.write(chunk)
            tmp_path = tmp.name
        for _ in range(concurrency):
            job = transcribe_task.apply_async(args=[tmp_path], kwargs={
                "from_url": False, "language": language, "task": task,
                "temperature": temperature, "save": save, "model_name": model_name
            })
            jobs.append(job.id)
    elif url:
        for _ in range(concurrency):
            job = transcribe_task.apply_async(args=[url], kwargs={
                "from_url": True, "language": language, "task": task,
                "temperature": temperature, "save": save, "model_name": model_name
            })
            jobs.append(job.id)
    else:
        raise HTTPException(status_code=400, detail="Dosya veya URL belirtilmeli")

    return {"job_ids": jobs}


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    job = celery_app.AsyncResult(job_id)
    if job.state == "PENDING":
        return {"status": "pending"}
    elif job.state == "STARTED":
        return {"status": "processing"}
    elif job.state == "FAILURE":
        return {"status": "failed", "error": str(job.info)}
    elif job.state == "SUCCESS":
        result = job.result
        if isinstance(result, dict):
            # segments'i chunks formatına çevir
            chunks = []
            if "segments" in result and result["segments"]:
                for segment in result["segments"]:
                    chunks.append({
                        "timestamp": [segment.get("start", 0.0), segment.get("end", 0.0)],
                        "text": segment.get("text", "").strip()
                    })
            
            # text, chunks ve saved_file döndür
            filtered_result = {
                "text": result.get("text", ""),
                "chunks": chunks,
                "saved_file": result.get("saved_file")
            }
            return {"status": "done", "result": filtered_result}
        return {"status": "done", "result": result}
