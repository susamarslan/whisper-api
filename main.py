from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import tempfile
from tasks import transcribe_task, celery_app

app = FastAPI()

def format_time(seconds):
    """Saniyeyi VTT formatına (HH:MM:SS.mmm) çevirir"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

def generate_vtt(segments):
    """Segment listesinden VTT formatı oluşturur"""
    vtt_lines = ["WEBVTT", ""]
    for segment in segments:
        start_time = format_time(segment["start"])
        end_time = format_time(segment["end"])
        vtt_lines.append(f"{start_time} --> {end_time}")
        vtt_lines.append(segment["text"])
        vtt_lines.append("")
    return "\n".join(vtt_lines)

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
        return {"status": "done", "result": result}
