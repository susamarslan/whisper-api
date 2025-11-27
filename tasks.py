from faster_whisper import WhisperModel
import tempfile
import requests
import os
import shutil
import math
from celery import Celery
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

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
    
    # Segments generator'ı listeye çevir (bir kez iterate edilebilir)
    # Bu işlemi try bloğundan önce yapıyoruz ki except bloğunda kullanabilelim
    segments_list = list(segments)
    text = " ".join([segment.text for segment in segments_list])
    
    try:
        # Segment bilgilerini sakla
        segments_data = [{"start": segment.start, "end": segment.end, "text": segment.text} for segment in segments_list]
        
        # Saniyeyi VTT zaman formatına (HH:MM:SS.mmm) çeviren fonksiyon
        def format_timestamp(seconds):
            hours = math.floor(seconds / 3600)
            seconds %= 3600
            minutes = math.floor(seconds / 60)
            seconds %= 60
            milliseconds = round((seconds - math.floor(seconds)) * 1000)
            seconds = math.floor(seconds)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        
        # VTT formatı oluştur (WEBVTT header olmadan)
        vtt_lines = []
        for segment in segments_data:
            start_time = format_timestamp(segment["start"])
            end_time = format_timestamp(segment["end"])
            segment_text = segment["text"].strip()
            vtt_lines.append(f"{start_time} --> {end_time}")
            vtt_lines.append(f"{segment_text}")
            vtt_lines.append("")
        vtt_content = "\n".join(vtt_lines)
        
        # VTT dosyası kaydedilmiyor (kullanıcı isteği)
        vtt_file = None
        
        result = {
            "text": text,
            "segments": segments_data,
            "vtt": vtt_content,
            "saved_file": final_path if save else None,
            "saved_vtt_file": vtt_file
        }
        return result
    except Exception as e:
        # Hata durumunda logla ve sadece text döndür
        import traceback
        logger.error(f"VTT oluşturma hatası: {e}")
        logger.error(traceback.format_exc())
        # segments_list zaten yukarıda oluşturuldu, onu kullan
        return {
            "text": text,
            "saved_file": final_path if save else None,
            "error": str(e)
        }
