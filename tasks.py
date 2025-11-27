from faster_whisper import WhisperModel
import tempfile
import requests
import os
import shutil
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "whisper",
    broker=REDIS_URL,
    backend=REDIS_URL
)

model_cache = {}
SAVE_DIR = "/var/recordings"
os.makedirs(SAVE_DIR, exist_ok=True)

def get_model(name="base"):
    if name not in model_cache:
        model_cache[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return model_cache[name]


@celery_app.task
def transcribe_task(source, from_url=False, language=None, task="transcribe", temperature=0.0, save=False, model_name="base"):
    model = get_model(model_name)

    if from_url:
        r = requests.get(source, stream=True)
        if r.status_code != 200:
            return {"error": "Dosya indirilemedi"}
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            for chunk in r.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = tmp.name
    else:
        tmp_path = source
        if not os.path.exists(tmp_path):
            return {"error": "Dosya bulunamadı"}

    final_path = tmp_path
    if save:
        filename = os.path.basename(tmp_path)
        final_path = os.path.join(SAVE_DIR, filename)
        if os.path.exists(tmp_path):
            shutil.copy2(tmp_path, final_path)
            if tmp_path != final_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            return {"error": "Kaynak dosya bulunamadı"}

    if not os.path.exists(final_path):
        return {"error": "İşlenecek dosya bulunamadı"}

    segments, info = model.transcribe(
        final_path,
        language=language,
        task=task,
        temperature=temperature
    )
    
    # Segment bilgilerini sakla
    segments_list = [{"start": segment.start, "end": segment.end, "text": segment.text} for segment in segments]
    
    # Faster-Whisper segments döndürür, bunları birleştirmemiz gerekir
    text = " ".join([segment.text for segment in segments])
    
    # VTT formatı oluştur
    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    
    vtt_lines = ["WEBVTT", ""]
    for segment in segments_list:
        start_time = format_time(segment["start"])
        end_time = format_time(segment["end"])
        vtt_lines.append(f"{start_time} --> {end_time}")
        vtt_lines.append(segment["text"])
        vtt_lines.append("")
    vtt_content = "\n".join(vtt_lines)
    
    # VTT dosyasını kaydet
    vtt_file = None
    if save:
        base_name = os.path.splitext(os.path.basename(final_path))[0]
        vtt_file = os.path.join(SAVE_DIR, f"{base_name}.vtt")
        with open(vtt_file, "w", encoding="utf-8") as f:
            f.write(vtt_content)
    
    return {
        "text": text,
        "segments": segments_list,
        "vtt": vtt_content,
        "saved_file": final_path if save else None,
        "saved_vtt_file": vtt_file
    }
